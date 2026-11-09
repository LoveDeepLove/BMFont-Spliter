import re
import shutil
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from PIL import Image

# 匹配 BMFont 文本格式中的 char 行
char_line_pattern = re.compile(
    r"^char\s+id=(\d+)\s+x=(\d+)\s+y=(\d+)\s+width=(\d+)\s+height=(\d+)\b"
)
invalid_filename_chars = set('<>:"/\\|?*')
reserved_names = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}
cjk_ascii_punctuation_map = {
    ":": "：",
    ",": "，",
    ".": "。",
    ";": "；",
    "?": "？",
    "!": "！",
}
# Unity .fontsettings 中字符区块的起始行（可能是 serializedVersion 也可能是 index）
yaml_char_section = "m_CharacterRects"


@dataclass
class Glyph:
    """单个字符在图集中的像素矩形。"""

    char_id: int
    x: int
    y: int
    width: int
    height: int
    flipped: bool = False


@dataclass
class FontDescriptor:
    """解析后的字体描述，用于屏蔽 .fnt 与 .fontsettings 的格式差异。"""

    source: str  # "fnt" | "fontsettings"
    glyphs: list[Glyph]
    is_unicode_font: bool
    likely_cjk_font: bool
    warnings: list[str] = field(default_factory=list)


def decode_char_from_id(char_id: int, is_unicode_font: bool) -> str | None:
    """把 BMFont 的 char_id 还原为字符。"""
    if is_unicode_font:
        try:
            return chr(char_id)
        except ValueError:
            return None

    # ANSI 模式：先尝试单字节（ASCII/扩展字符）
    if 0 <= char_id <= 0xFF:
        try:
            return bytes([char_id]).decode("gbk")
        except UnicodeDecodeError:
            return None

    # 兼容部分错误标记为 unicode=0 的字体：char_id 实际直接存的是 Unicode 码点
    try:
        unicode_char = chr(char_id)
        if unicode_char.isprintable() and not unicode_char.isspace():
            return unicode_char
    except ValueError:
        pass

    # ANSI 模式中文常见为双字节编码值
    high = (char_id >> 8) & 0xFF
    low = char_id & 0xFF
    candidates = (
        bytes([high, low]),
        bytes([low, high]),
    )
    for b in candidates:
        try:
            return b.decode("gbk")
        except UnicodeDecodeError:
            continue
    return None


def to_readable_filename(char_id: int, is_unicode_font: bool) -> str:
    """把 char_id 转为可用于文件名的可读形式。"""
    ch = decode_char_from_id(char_id, is_unicode_font)
    if ch is None:
        return f"U+{char_id:04X}"

    # 避免多字符结果导致异常命名（理论上单个 glyph 应对应单个字符）
    if len(ch) != 1:
        return f"U+{char_id:04X}"

    # Windows 文件名不允许的字符，或不可见字符，统一回退到码点格式
    if ch in invalid_filename_chars or ch.isspace() or not ch.isprintable():
        return f"U+{char_id:04X}"
    return ch


def safe_filename_base(name: str, char_id: int) -> str:
    """将字符名清洗为 Windows 可用的文件名基础部分。"""
    # 尽量保留原始字符命名，仅去掉首尾空白；结尾的点与空格会被 Windows 丢弃
    cleaned = name.strip().rstrip(". ")
    if not cleaned:
        return f"U+{char_id:04X}"

    if cleaned.upper() in reserved_names:
        return f"{cleaned}_{char_id}"

    return cleaned


def is_cjk_codepoint(char_id: int) -> bool:
    """判断码点是否落在常见 CJK 区段。"""
    if char_id <= 255:
        return False
    try:
        ch = chr(char_id)
    except ValueError:
        return False
    return (
        ("\u4e00" <= ch <= "\u9fff")
        or ("\u3400" <= ch <= "\u4dbf")
        or ("\uf900" <= ch <= "\ufaff")
    )


def to_float(value) -> float:
    """把 YAML 中的标量安全转成 float。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_flow_mapping(raw: str) -> dict[str, str]:
    """解析 Unity YAML 的流式映射，如 {serializedVersion: 2, x: 0, width: 1}。"""
    raw = raw.strip()
    if not raw.startswith("{"):
        return {}
    body = raw[1:-1] if raw.endswith("}") else raw[1:]
    result: dict[str, str] = {}
    for part in body.split(","):
        if ":" not in part:
            continue
        key, _, value = part.partition(":")
        result[key.strip()] = value.strip()
    return result


def iter_yaml_list_items(text: str, section: str) -> list[list[str]]:
    """从 Unity YAML 中取出指定键下的列表，每个元素返回其行集合。"""
    lines = text.splitlines()
    start = -1
    base_indent = 0
    for idx, line in enumerate(lines):
        if line.strip() == f"{section}:":
            start = idx + 1
            base_indent = len(line) - len(line.lstrip())
            break
    if start < 0:
        return []

    items: list[list[str]] = []
    current: list[str] | None = None
    for line in lines[start:]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        item_match = re.match(r"^(\s*)-\s+", line)
        if item_match:
            if current is not None:
                items.append(current)
            # 去掉 "- "，保留该元素首行内容
            current = [line[item_match.end():]]
            continue
        if indent <= base_indent:
            break  # 已经走出该列表所属的区块
        if current is not None:
            current.append(line)
    if current is not None:
        items.append(current)
    return items


def parse_character_rect(lines: list[str]) -> dict:
    """解析单条 m_CharacterRects 元素，兼容 block / flow 两种写法。"""
    data: dict = {}
    sub_key: str | None = None
    for raw in lines:
        body = raw.strip()
        if not body or body.startswith("#") or ":" not in body:
            continue
        indent = len(raw) - len(raw.lstrip())
        key, _, value = body.partition(":")
        key, value = key.strip(), value.strip()

        if sub_key is not None and indent >= 6:
            data[sub_key][key] = value
            continue

        sub_key = None
        if value == "":
            data[key] = {}
            sub_key = key
        elif value.startswith("{"):
            data[key] = parse_flow_mapping(value)
        else:
            data[key] = value
    return data


def read_fnt_descriptor(fnt_path: Path) -> FontDescriptor:
    """读取 BMFont 文本格式 .fnt。"""
    is_unicode = False
    glyphs: list[Glyph] = []
    with fnt_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("info "):
                is_unicode = "unicode=1" in stripped
                continue
            match = char_line_pattern.match(stripped)
            if not match:
                continue
            char_id, x, y, width, height = map(int, match.groups())
            glyphs.append(Glyph(char_id, x, y, width, height))

    has_cjk = any(is_cjk_codepoint(g.char_id) for g in glyphs)
    return FontDescriptor("fnt", glyphs, is_unicode, has_cjk)


def read_fontsettings_descriptor(
    settings_path: Path, atlas_size: tuple[int, int]
) -> FontDescriptor:
    """读取 Unity 文本序列化的 .fontsettings 资源。"""
    text = settings_path.read_text(encoding="utf-8", errors="ignore")
    items = iter_yaml_list_items(text, yaml_char_section)
    if not items:
        if "!u!128" not in text:
            raise ValueError(
                "该文件不是 Unity 字体资源（缺少 !u!128 Font 标记），请选择 .fontsettings 文件。"
            )
        raise ValueError(
            "该 .fontsettings 中 m_CharacterRects 为空，没有可拆分的字符数据。"
        )

    atlas_w, atlas_h = atlas_size
    glyphs: list[Glyph] = []
    skipped = 0
    clamped = 0

    for item in items:
        rect = parse_character_rect(item)
        if "index" not in rect:
            continue
        char_id = int(to_float(rect.get("index")))
        if char_id < 0:
            continue

        uv = rect.get("uv") or {}
        vert = rect.get("vert") or {}
        uv_w = to_float(uv.get("width"))
        uv_h = to_float(uv.get("height"))

        # uv 为归一化坐标（原点在左下），vert 为像素尺寸（高度通常是负数）
        if uv_w > 0 and uv_h > 0:
            width = round(uv_w * atlas_w)
            height = round(uv_h * atlas_h)
        else:
            width = round(abs(to_float(vert.get("width"))))
            height = round(abs(to_float(vert.get("height"))))

        if width <= 0 or height <= 0:
            skipped += 1  # 空格等未配置字形
            continue

        x = round(to_float(uv.get("x")) * atlas_w)
        # Unity 纹理原点在左下，PNG 原点在左上，需要按 Y 轴翻转
        y = round(atlas_h - (to_float(uv.get("y")) + uv_h) * atlas_h)

        if x < 0 or y < 0 or x + width > atlas_w or y + height > atlas_h:
            clamped += 1
            x = max(0, min(x, atlas_w - 1))
            y = max(0, min(y, atlas_h - 1))
            width = max(1, min(width, atlas_w - x))
            height = max(1, min(height, atlas_h - y))

        flipped = int(to_float(rect.get("flipped"))) != 0
        glyphs.append(Glyph(char_id, x, y, width, height, flipped))

    warnings: list[str] = []
    if skipped:
        warnings.append(f"跳过 {skipped} 个宽高为 0 的未配置字形")
    if clamped:
        warnings.append(f"{clamped} 个字形超出图集范围，已裁剪到边界内")

    has_cjk = any(is_cjk_codepoint(g.char_id) for g in glyphs)
    # .fontsettings 的 index 恒为 Unicode 码点
    return FontDescriptor("fontsettings", glyphs, True, has_cjk, warnings)


def load_descriptor(
    descriptor_path: Path, atlas_size: tuple[int, int]
) -> FontDescriptor:
    """按文件内容自动识别 .fnt / .fontsettings 并解析。"""
    with descriptor_path.open("rb") as f:
        head = f.read(4096)
    if not head.strip():
        raise ValueError("字体描述文件内容为空。")

    text_head = head.decode("utf-8", errors="ignore")
    stripped_head = text_head.lstrip()

    if stripped_head.startswith("%YAML") or yaml_char_section in text_head:
        return read_fontsettings_descriptor(descriptor_path, atlas_size)

    if "id=" in text_head and "char " in text_head:
        return read_fnt_descriptor(descriptor_path)

    if b"\x00" in head[:64]:
        raise ValueError(
            "该 .fontsettings 使用二进制序列化，暂不支持解析。\n\n"
            "解决办法：Unity 菜单 Project Settings → Editor → Asset Serialization "
            "改为 Force Text，重新导入资源后即可解析。"
        )

    raise ValueError(
        "无法识别的字体描述文件，仅支持 BMFont 文本 .fnt 与 Unity 文本 .fontsettings。"
    )


# ---------------- 打包：散图 → 图集 + 字体描述 ----------------

pack_padding = 2  # 与参考工具一致：每格比图片大 2px，四周各留 1px
max_atlas_size = 4096

unicode_stem_pattern = re.compile(r"^(?:u\+|uni|0x)([0-9a-fA-F]{2,6})$", re.IGNORECASE)

# 未指定模板时的兜底模板；材质引用为空，需在 Unity 中手动指定
default_fontsettings_template = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!128 &12800000
Font:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {fileID: 0}
  m_PrefabInstance: {fileID: 0}
  m_PrefabAsset: {fileID: 0}
  m_Name: FontName
  serializedVersion: 5
  m_LineSpacing: 0.1
  m_DefaultMaterial: {fileID: 0}
  m_FontSize: 0
  m_Texture: {fileID: 0}
  m_AsciiStartOffset: 0
  m_Tracking: 1
  m_CharacterSpacing: 0
  m_CharacterPadding: 1
  m_ConvertCase: 0
  m_CharacterRects:
  m_KerningValues: []
  m_PixelScale: 0.1
  m_FontData:
  m_Ascent: 0
  m_Descent: 0
  m_DefaultStyle: 0
  m_FontNames: []
  m_FallbackFonts: []
  m_FontRenderingMode: 0
  m_UseLegacyBoundsCalculation: 0
  m_ShouldRoundAdvanceValue: 1
"""


@dataclass
class GlyphSource:
    """待打包的单个字形图片。"""

    char_id: int
    stem: str
    image: Image.Image


@dataclass
class PlacedGlyph:
    """装箱结果；width/height 已包含 padding。"""

    char_id: int
    x: int
    y: int
    width: int
    height: int

    @property
    def image_width(self) -> int:
        return self.width - pack_padding

    @property
    def image_height(self) -> int:
        return self.height - pack_padding


@dataclass
class PackResult:
    atlas_path: Path
    fnt_path: Path | None
    fontsettings_path: Path | None
    glyph_count: int
    atlas_size: tuple[int, int]
    warnings: list[str] = field(default_factory=list)


def parse_char_id_from_stem(stem: str) -> tuple[int, bool]:
    """由文件名推导字符编码，返回 (编码, 是否精确匹配)。"""
    match = unicode_stem_pattern.match(stem.strip())
    if match:
        return int(match.group(1), 16), True
    if len(stem) == 1:
        return ord(stem), True
    # 与参考工具一致：多字符文件名取首字符
    return ord(stem[0]), False


def load_glyph_images(input_dir: Path) -> tuple[list[GlyphSource], list[str]]:
    """读取目录下的散图，文件名即字符。"""
    glyphs: list[GlyphSource] = []
    warnings: list[str] = []
    seen: dict[int, str] = {}

    for path in sorted(input_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
            continue
        char_id, exact = parse_char_id_from_stem(path.stem)
        if not exact:
            warnings.append(
                f"「{path.name}」文件名含多个字符，已按首字符 {chr(char_id)}（U+{char_id:04X}）处理"
            )
        if char_id in seen:
            warnings.append(f"字符 U+{char_id:04X} 重复（{seen[char_id]} 与 {path.name}），已跳过后者")
            continue
        try:
            with Image.open(path) as source:
                image = source.convert("RGBA")
        except Exception:
            warnings.append(f"「{path.name}」无法读取，已跳过")
            continue
        if image.width <= 0 or image.height <= 0:
            warnings.append(f"「{path.name}」尺寸为 0，已跳过")
            continue
        seen[char_id] = path.name
        glyphs.append(GlyphSource(char_id, path.stem, image))

    return glyphs, warnings


def initial_atlas_size(glyphs: list[GlyphSource]) -> tuple[int, int]:
    """按总面积推导 2 的幂尺寸，与参考工具的策略一致。"""
    total = sum(
        (g.image.width + pack_padding) * (g.image.height + pack_padding) for g in glyphs
    )
    power_w = 1
    power_h = 1
    while total > (2**power_w) * (2**power_h):
        if power_w <= power_h:
            power_w += 1
        else:
            power_h += 1
    return 2**power_w, 2**power_h


def prune_free_rects(rects: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """去掉被其它空闲矩形完全包含的矩形。"""
    kept = []
    for index, rect in enumerate(rects):
        contained = False
        for other_index, other in enumerate(rects):
            if index == other_index:
                continue
            inside = (
                rect[0] >= other[0]
                and rect[1] >= other[1]
                and rect[0] + rect[2] <= other[0] + other[2]
                and rect[1] + rect[3] <= other[1] + other[3]
            )
            if inside and (rect != other or other_index < index):
                contained = True
                break
        if not contained:
            kept.append(rect)
    return kept


def max_rects_pack(
    items: list[tuple[int, int, int]],
    bin_width: int,
    bin_height: int,
    heuristic: str,
) -> dict[int, tuple[int, int, int, int]] | None:
    """MaxRects 装箱；items 为 (序号, 宽, 高)，宽高已含 padding。"""
    free = [(0, 0, bin_width, bin_height)]
    placed: dict[int, tuple[int, int, int, int]] = {}

    for item_id, width, height in sorted(items, key=lambda it: max(it[1], it[2]), reverse=True):
        best_rect = None
        best_score = None
        for free_x, free_y, free_w, free_h in free:
            if width > free_w or height > free_h:
                continue
            leftover_w = free_w - width
            leftover_h = free_h - height
            if heuristic == "bssf":
                score = (min(leftover_w, leftover_h), max(leftover_w, leftover_h))
            elif heuristic == "baf":
                score = (free_w * free_h - width * height, min(leftover_w, leftover_h))
            else:  # bl：尽量靠左下
                score = (free_y + height, free_x)
            if best_score is None or score < best_score:
                best_score = score
                best_rect = (free_x, free_y)
        if best_rect is None:
            return None

        place_x, place_y = best_rect
        placed[item_id] = (place_x, place_y, width, height)

        new_free = []
        for rect_x, rect_y, rect_w, rect_h in free:
            if (
                place_x >= rect_x + rect_w
                or place_x + width <= rect_x
                or place_y >= rect_y + rect_h
                or place_y + height <= rect_y
            ):
                new_free.append((rect_x, rect_y, rect_w, rect_h))
                continue
            if place_y > rect_y:
                new_free.append((rect_x, rect_y, rect_w, place_y - rect_y))
            if place_y + height < rect_y + rect_h:
                new_free.append(
                    (rect_x, place_y + height, rect_w, rect_y + rect_h - (place_y + height))
                )
            if place_x > rect_x:
                new_free.append((rect_x, rect_y, place_x - rect_x, rect_h))
            if place_x + width < rect_x + rect_w:
                new_free.append(
                    (place_x + width, rect_y, rect_x + rect_w - (place_x + width), rect_h)
                )
        free = prune_free_rects(new_free)

    return placed


def pack_glyphs(
    glyphs: list[GlyphSource],
) -> tuple[list[PlacedGlyph], tuple[int, int]]:
    """装箱并按需放大图集，返回排布结果与图集尺寸。"""
    items = [
        (index, g.image.width + pack_padding, g.image.height + pack_padding)
        for index, g in enumerate(glyphs)
    ]
    atlas_width, atlas_height = initial_atlas_size(glyphs)

    while True:
        for heuristic in ("bssf", "baf", "bl"):
            placed = max_rects_pack(items, atlas_width, atlas_height, heuristic)
            if placed is not None:
                result = [
                    PlacedGlyph(
                        glyphs[index].char_id,
                        *placed[index],
                    )
                    for index, _, _ in items
                ]
                return result, (atlas_width, atlas_height)
        if atlas_width >= max_atlas_size and atlas_height >= max_atlas_size:
            raise ValueError(
                f"图片太多或太大，{max_atlas_size}x{max_atlas_size} 的图集也放不下。"
            )
        if atlas_width <= atlas_height:
            atlas_width = min(atlas_width * 2, max_atlas_size)
        else:
            atlas_height = min(atlas_height * 2, max_atlas_size)


def build_atlas_image(
    glyphs: list[GlyphSource],
    placed: list[PlacedGlyph],
    size: tuple[int, int],
) -> Image.Image:
    """把散图直接覆盖到图集对应位置（保留 alpha，不做混合）。"""
    atlas = Image.new("RGBA", size, (0, 0, 0, 0))
    by_char_id = {g.char_id: g for g in glyphs}
    for item in placed:
        glyph = by_char_id[item.char_id]
        atlas.paste(glyph.image, (item.x, item.y))
    return atlas


def fmt_num(value: float) -> str:
    """输出 Unity YAML 惯用的紧凑数字。"""
    if abs(value) < 1e-9:
        return "0"
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def write_fnt_file(
    path: Path,
    font_name: str,
    png_name: str,
    placed: list[PlacedGlyph],
    atlas_size: tuple[int, int],
    space_width: int,
    line_height: int,
) -> None:
    """按 BMFont 文本格式输出，字段与参考工具保持一致。"""
    atlas_w, atlas_h = atlas_size
    offset = pack_padding // 2
    lines = [
        f'info face="{font_name}" size=0 bold=0 italic=0 charset="ANSI" unicode=0 '
        "stretchH=0 smooth=1 aa=1 padding=0,0,0,0 spacing=0,0",
        f"common lineHeight={line_height} base=0 scaleW={atlas_w} scaleH={atlas_h} "
        "pages=1 packed=0",
        f'page id=0 file="{png_name}"',
        f"chars count={len(placed) + 1}",
        "",
        f"char  id=32  x=0  y=0  width=0  height=0  xoffset=0  yoffset=0  "
        f"xadvance={space_width}  page=0  chnl=0",
    ]
    for item in sorted(placed, key=lambda it: it.char_id):
        lines.append(
            f"char  id={item.char_id}  x={item.x}  y={item.y}  "
            f"width={item.image_width}  height={item.image_height}  "
            f"xoffset={offset}  yoffset={offset}  xadvance={item.image_width}  "
            f"page=0  chnl=0"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_character_rects_yaml(
    placed: list[PlacedGlyph], atlas_size: tuple[int, int]
) -> list[str]:
    """生成 m_CharacterRects 的条目，uv 为归一化坐标且 Y 轴翻转。"""
    atlas_w, atlas_h = atlas_size
    lines: list[str] = []
    for item in sorted(placed, key=lambda it: it.char_id):
        width = item.image_width
        height = item.image_height
        uv_x = item.x / atlas_w
        uv_w = width / atlas_w
        uv_h = height / atlas_h
        uv_y = 1 - (item.y / atlas_h) - uv_h
        lines.extend(
            [
                "  - serializedVersion: 2",
                f"    index: {item.char_id}",
                "    uv:",
                "      serializedVersion: 2",
                f"      x: {fmt_num(uv_x)}",
                f"      y: {fmt_num(uv_y)}",
                f"      width: {fmt_num(uv_w)}",
                f"      height: {fmt_num(uv_h)}",
                "    vert:",
                "      serializedVersion: 2",
                "      x: 0",
                f"      y: {height}",
                f"      width: {width}",
                f"      height: {-height}",
                f"    advance: {width}",
                "    flipped: 0",
            ]
        )
    return lines


def write_fontsettings_file(
    path: Path,
    font_name: str,
    template_text: str,
    placed: list[PlacedGlyph],
    atlas_size: tuple[int, int],
) -> None:
    """以模板为基底，只替换字体名与字符表，保留引擎自定义的 YAML 头。"""
    text = re.sub(
        r"^(\s*m_Name: ).*$",
        lambda m: m.group(1) + font_name,
        template_text,
        count=1,
        flags=re.MULTILINE,
    )

    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "m_CharacterRects:" or stripped == "m_CharacterRects: []":
            start = index
            break
    if start is None:
        raise ValueError("模板 .fontsettings 中缺少 m_CharacterRects 字段。")

    end = start + 1
    while end < len(lines):
        line = lines[end]
        if not line.strip() or line.startswith("  - ") or line.startswith("    "):
            end += 1
            continue
        break

    entries = build_character_rects_yaml(placed, atlas_size)
    new_lines = lines[: start + 1] + entries + lines[end:]
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def generate_font_package(
    input_dir: Path,
    output_dir: Path,
    font_name: str,
    export_fnt: bool = True,
    export_fontsettings: bool = False,
    template_path: Path | None = None,
    space_width: int | None = None,
    line_height: int | None = None,
) -> PackResult:
    """把散图打包为图集（png）并按需输出 .fnt / .fontsettings。"""
    glyphs, warnings = load_glyph_images(input_dir)
    if not glyphs:
        raise ValueError("所选目录下没有可用的图片（支持 png/jpg/jpeg/bmp）。")
    if not export_fnt and not export_fontsettings:
        raise ValueError("请至少勾选一种输出文件（.fnt 或 .fontsettings）。")

    placed, atlas_size = pack_glyphs(glyphs)
    output_dir.mkdir(parents=True, exist_ok=True)

    atlas = build_atlas_image(glyphs, placed, atlas_size)
    atlas_path = output_dir / f"{font_name}.png"
    atlas.save(atlas_path, format="PNG")

    if space_width is None:
        space_width = max(g.image.width for g in glyphs)
    if line_height is None:
        line_height = max(g.image.height for g in glyphs)

    fnt_path = None
    if export_fnt:
        fnt_path = output_dir / f"{font_name}.fnt"
        write_fnt_file(
            fnt_path,
            font_name,
            atlas_path.name,
            placed,
            atlas_size,
            space_width,
            line_height,
        )

    fontsettings_path = None
    if export_fontsettings:
        if template_path is not None:
            template_text = template_path.read_text(encoding="utf-8", errors="ignore")
            if "m_CharacterRects" not in template_text:
                raise ValueError("模板文件中没有 m_CharacterRects，请选择现有的 .fontsettings。")
        else:
            template_text = default_fontsettings_template
            warnings.append(
                "未指定 Unity 模板，已使用内置模板：材质引用为空，需在 Unity 中补 Default Material；"
                "若引擎使用自定义 YAML 头，请选择现有 .fontsettings 作为模板。"
            )
        fontsettings_path = output_dir / f"{font_name}.fontsettings"
        write_fontsettings_file(
            fontsettings_path, font_name, template_text, placed, atlas_size
        )

    return PackResult(
        atlas_path, fnt_path, fontsettings_path, len(glyphs), atlas_size, warnings
    )


def split_font_images(
    descriptor_path: Path,
    png_path: Path,
    output_dir: Path,
    export_format: str = "png",
) -> tuple[int, FontDescriptor]:
    """执行拆图逻辑，返回 (成功导出的图片数量, 字体描述信息)。"""
    export_format = export_format.lower()
    if export_format not in {"png", "jpg"}:
        raise ValueError("仅支持 png 或 jpg 格式导出。")

    image_format = "PNG" if export_format == "png" else "JPEG"
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_count = 0
    name_counter: dict[str, int] = {}

    with Image.open(png_path) as atlas:
        descriptor = load_descriptor(descriptor_path, atlas.size)
        if not descriptor.glyphs:
            raise ValueError("字体描述文件中没有可用的字符数据。")

        for glyph in descriptor.glyphs:
            if glyph.width <= 0 or glyph.height <= 0:
                continue

            char_id = glyph.char_id
            crop_img = atlas.crop(
                (glyph.x, glyph.y, glyph.x + glyph.width, glyph.y + glyph.height)
            )
            if glyph.flipped:
                crop_img = crop_img.transpose(Image.FLIP_TOP_BOTTOM)

            if descriptor.likely_cjk_font and 0 <= char_id <= 0xFF:
                ascii_char = chr(char_id)
                if ascii_char in cjk_ascii_punctuation_map:
                    readable_name = cjk_ascii_punctuation_map[ascii_char]
                else:
                    readable_name = to_readable_filename(
                        char_id, descriptor.is_unicode_font
                    )
            else:
                readable_name = to_readable_filename(
                    char_id, descriptor.is_unicode_font
                )
            base_name = safe_filename_base(readable_name, char_id)

            # 处理重名，避免覆盖同名字符图
            index = name_counter.get(base_name, 0)
            name_counter[base_name] = index + 1
            if index == 0:
                filename = f"{base_name}.{export_format}"
            else:
                filename = f"{base_name}_{index}.{export_format}"

            # 显式指定格式，避免 Pillow 依赖扩展名推断失败
            if image_format == "JPEG" and crop_img.mode in ("RGBA", "LA", "P"):
                crop_img = crop_img.convert("RGB")
            crop_img.save(output_dir / filename, format=image_format)
            saved_count += 1

    return saved_count, descriptor


def clear_output_dir(output_dir: Path) -> None:
    """清空输出目录内的所有文件和子目录。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    for item in output_dir.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


class FontSplitterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("字体图集工具（拆分 / 打包）")
        self.root.geometry("760x430")
        self.root.resizable(False, False)

        # 拆分页
        self.descriptor_var = tk.StringVar()
        self.png_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.export_format_var = tk.StringVar(value="png")
        self.status_var = tk.StringVar(
            value="请选择字体描述文件（.fnt / .fontsettings）、png 和输出目录。"
        )

        # 打包页
        self.pack_input_var = tk.StringVar()
        self.pack_output_var = tk.StringVar()
        self.pack_name_var = tk.StringVar()
        self.pack_space_var = tk.StringVar()
        self.pack_height_var = tk.StringVar()
        self.pack_fnt_var = tk.BooleanVar(value=True)
        self.pack_fontsettings_var = tk.BooleanVar(value=True)
        self.pack_template_var = tk.StringVar()
        self.pack_status_var = tk.StringVar(
            value="选择散图目录：文件名即字符，如 万.png、A.png、U+4E07.png。"
        )

        self._build_ui()

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.split_tab = ttk.Frame(notebook)
        self.pack_tab = ttk.Frame(notebook)
        notebook.add(self.split_tab, text="  拆分：字体 → 图片  ")
        notebook.add(self.pack_tab, text="  打包：图片 → 字体  ")

        self._build_split_ui()
        self._build_pack_ui()

    def _build_split_ui(self) -> None:
        tab = self.split_tab
        tab.grid_columnconfigure(1, weight=1)

        self._build_row(tab, "字体描述文件:", self.descriptor_var, self.select_descriptor_file, 0)
        self._build_row(tab, "PNG 文件:", self.png_var, self.select_png_file, 1)
        self._build_row(tab, "输出目录:", self.output_var, self.select_output_dir, 2)
        self._build_output_warning_row(tab, 3)
        self._build_format_row(tab, 4)

        run_button = ttk.Button(tab, text="开始拆分", width=15, command=self.run_split)
        run_button.grid(row=5, column=1, padx=10, pady=15, sticky="w")

        status_label = ttk.Label(tab, textvariable=self.status_var, foreground="blue", anchor="w")
        status_label.grid(row=6, column=0, columnspan=3, padx=10, pady=(0, 10), sticky="we")

    def _build_pack_ui(self) -> None:
        tab = self.pack_tab
        tab.grid_columnconfigure(1, weight=1)

        self._build_row(tab, "散图目录:", self.pack_input_var, self.select_pack_input, 0)
        self._build_row(tab, "输出目录:", self.pack_output_var, self.select_pack_output, 1)
        self._build_row(
            tab, "字体名称:", self.pack_name_var, None, 2, editable=True
        )
        self._build_row(
            tab, "Unity 模板:", self.pack_template_var, self.select_pack_template, 3
        )

        metrics = ttk.Frame(tab)
        metrics.grid(row=4, column=1, padx=10, pady=6, sticky="w")
        ttk.Label(metrics, text="空格宽度:").pack(side="left")
        ttk.Entry(metrics, textvariable=self.pack_space_var, width=8).pack(
            side="left", padx=(4, 18)
        )
        ttk.Label(metrics, text="行高 lineHeight:").pack(side="left")
        ttk.Entry(metrics, textvariable=self.pack_height_var, width=8).pack(
            side="left", padx=(4, 0)
        )
        ttk.Label(metrics, text="留空则自动取最大图", foreground="#6b7280").pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(tab, text="排版:").grid(row=4, column=0, padx=10, pady=8, sticky="w")

        options = ttk.Frame(tab)
        options.grid(row=5, column=1, padx=10, pady=6, sticky="w")
        ttk.Checkbutton(options, text=".fnt（BMFont）", variable=self.pack_fnt_var).pack(
            side="left"
        )
        ttk.Checkbutton(
            options, text=".fontsettings（Unity）", variable=self.pack_fontsettings_var
        ).pack(side="left", padx=(18, 0))
        ttk.Label(tab, text="输出文件:").grid(row=5, column=0, padx=10, pady=8, sticky="w")

        hint = (
            "提示：只写入 <字体名>.png / .fnt / .fontsettings，同名文件会被覆盖。"
            "Unity 模板可选，建议选择同目录下现有的 .fontsettings，以沿用引擎自定义的 YAML 头与材质引用。"
        )
        ttk.Label(
            tab,
            text=hint,
            foreground="#b45309",
            wraplength=680,
            anchor="w",
            justify="left",
        ).grid(row=6, column=0, columnspan=3, padx=10, pady=(2, 6), sticky="we")

        ttk.Button(tab, text="开始打包", width=15, command=self.run_pack).grid(
            row=7, column=1, padx=10, pady=10, sticky="w"
        )

        ttk.Label(
            tab,
            textvariable=self.pack_status_var,
            foreground="blue",
            anchor="w",
            wraplength=680,
            justify="left",
        ).grid(row=8, column=0, columnspan=3, padx=10, pady=(0, 10), sticky="we")

    def _build_row(
        self,
        parent,
        label_text: str,
        var: tk.StringVar,
        browse_cmd,
        row_idx: int,
        editable: bool = False,
    ) -> None:
        label = ttk.Label(parent, text=label_text)
        label.grid(row=row_idx, column=0, padx=10, pady=8, sticky="w")

        entry = ttk.Entry(
            parent, textvariable=var, width=60, state="normal" if editable else "readonly"
        )
        entry.grid(row=row_idx, column=1, padx=10, pady=8, sticky="we")

        if browse_cmd is not None:
            browse_button = ttk.Button(parent, text="浏览", width=10, command=browse_cmd)
            browse_button.grid(row=row_idx, column=2, padx=10, pady=8)

    def _build_output_warning_row(self, parent, row_idx: int) -> None:
        hint = (
            "提示：开始拆分前会先清空所选输出目录下的全部文件与子目录，再写入新图片；"
            "请勿选择含重要数据的文件夹。"
        )
        warn_label = ttk.Label(
            parent,
            text=hint,
            foreground="#b45309",
            wraplength=680,
            anchor="w",
            justify="left",
        )
        warn_label.grid(row=row_idx, column=0, columnspan=3, padx=10, pady=(0, 6), sticky="we")

    def _build_format_row(self, parent, row_idx: int) -> None:
        label = ttk.Label(parent, text="导出格式:")
        label.grid(row=row_idx, column=0, padx=10, pady=8, sticky="w")

        frame = ttk.Frame(parent)
        frame.grid(row=row_idx, column=1, padx=10, pady=8, sticky="w")

        png_radio = ttk.Radiobutton(frame, text="PNG", value="png", variable=self.export_format_var)
        png_radio.pack(side="left")

        jpg_radio = ttk.Radiobutton(frame, text="JPG", value="jpg", variable=self.export_format_var)
        jpg_radio.pack(side="left", padx=(16, 0))

    def select_descriptor_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择字体描述文件",
            filetypes=[
                ("字体描述文件", "*.fnt *.fontsettings"),
                ("BMFont 文本 (.fnt)", "*.fnt"),
                ("Unity 字体 (.fontsettings)", "*.fontsettings"),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            self.descriptor_var.set(path)
            suffix = Path(path).suffix.lower()
            if suffix == ".fontsettings":
                self.status_var.set(
                    "已选择 Unity .fontsettings（文本格式），请再选择配套的图集 png。"
                )
            elif suffix == ".fnt":
                self.status_var.set("已选择 BMFont .fnt，请再选择配套的图集 png。")
            else:
                self.status_var.set("已选择字体描述文件，将按内容自动识别格式。")

    def select_png_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 PNG 文件",
            filetypes=[("PNG 图片", "*.png"), ("所有文件", "*.*")],
        )
        if path:
            self.png_var.set(path)

    def select_output_dir(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_var.set(path)

    def select_pack_input(self) -> None:
        path = filedialog.askdirectory(title="选择散图目录")
        if path:
            self.pack_input_var.set(path)
            if not self.pack_output_var.get().strip():
                self.pack_output_var.set(path)
            if not self.pack_name_var.get().strip():
                self.pack_name_var.set(Path(path).name or "newfont")
            self.pack_status_var.set("已选择散图目录，确认字体名称后点击「开始打包」。")

    def select_pack_output(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.pack_output_var.set(path)

    def select_pack_template(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 Unity 模板字体",
            filetypes=[("Unity 字体 (.fontsettings)", "*.fontsettings"), ("所有文件", "*.*")],
        )
        if path:
            self.pack_template_var.set(path)

    @staticmethod
    def parse_optional_int(value: str, label: str) -> int | None:
        """空串返回 None（表示自动计算），否则校验为非负整数。"""
        text = value.strip()
        if not text:
            return None
        try:
            number = int(text)
        except ValueError:
            raise ValueError(f"{label}必须是非负整数。") from None
        if number < 0:
            raise ValueError(f"{label}必须是非负整数。")
        return number

    def run_pack(self) -> None:
        input_value = self.pack_input_var.get().strip()
        output_value = self.pack_output_var.get().strip()
        font_name = self.pack_name_var.get().strip()
        template_value = self.pack_template_var.get().strip()

        if not input_value or not output_value or not font_name:
            messagebox.showwarning(
                "参数不完整", "请先选择散图目录、输出目录并填写字体名称。"
            )
            return

        input_dir = Path(input_value)
        output_dir = Path(output_value)
        if not input_dir.is_dir():
            messagebox.showerror("目录不存在", "散图目录无效。")
            return
        if any(ch in invalid_filename_chars for ch in font_name):
            messagebox.showerror("名称非法", '字体名称不能包含 < > : " / \\ | ? * 等字符。')
            return

        try:
            space_width = self.parse_optional_int(self.pack_space_var.get(), "空格宽度")
            line_height = self.parse_optional_int(self.pack_height_var.get(), "行高")
        except ValueError as e:
            messagebox.showerror("参数错误", str(e))
            return

        template_path = Path(template_value) if template_value else None
        if template_path is not None and not template_path.is_file():
            messagebox.showerror("文件不存在", "Unity 模板路径无效。")
            return

        try:
            result = generate_font_package(
                input_dir,
                output_dir,
                font_name,
                export_fnt=self.pack_fnt_var.get(),
                export_fontsettings=self.pack_fontsettings_var.get(),
                template_path=template_path,
                space_width=space_width,
                line_height=line_height,
            )
        except Exception as e:
            messagebox.showerror("执行失败", f"打包失败：{e}")
            self.pack_status_var.set("执行失败，请检查图片目录与参数。")
            return

        outputs = [result.atlas_path.name]
        if result.fnt_path:
            outputs.append(result.fnt_path.name)
        if result.fontsettings_path:
            outputs.append(result.fontsettings_path.name)

        summary = (
            f"共 {result.glyph_count} 个字形，图集 {result.atlas_size[0]}x{result.atlas_size[1]}，"
            f"已输出：{'、'.join(outputs)}。"
        )
        if result.warnings:
            summary += "\n" + "\n".join(f"· {w}" for w in result.warnings)

        self.pack_status_var.set(f"打包完成：{summary.splitlines()[0]}")
        messagebox.showinfo("完成", f"打包完成，{summary}")

    def run_split(self) -> None:
        descriptor_value = self.descriptor_var.get().strip()
        png_value = self.png_var.get().strip()
        output_value = self.output_var.get().strip()
        export_format = self.export_format_var.get().strip().lower()

        if not descriptor_value or not png_value or not output_value:
            messagebox.showwarning(
                "参数不完整", "请先选择字体描述文件、png 文件和输出目录。"
            )
            return

        descriptor_path = Path(descriptor_value)
        png_path = Path(png_value)
        output_dir = Path(output_value)

        if not descriptor_path.is_file():
            messagebox.showerror("文件不存在", "字体描述文件路径无效。")
            return
        if not png_path.is_file():
            messagebox.showerror("文件不存在", "png 文件路径无效。")
            return

        try:
            clear_output_dir(output_dir)
            count, descriptor = split_font_images(
                descriptor_path, png_path, output_dir, export_format
            )
        except Exception as e:
            messagebox.showerror("执行失败", f"拆分失败：{e}")
            self.status_var.set("执行失败，请检查文件格式和路径。")
            return

        source_text = (
            "Unity .fontsettings" if descriptor.source == "fontsettings" else "BMFont .fnt"
        )
        summary = (
            f"来源 {source_text}，共 {len(descriptor.glyphs)} 个字形，"
            f"已导出 {count} 张 {export_format.upper()} 图片。"
        )
        if descriptor.warnings:
            summary += "\n" + "\n".join(f"· {w}" for w in descriptor.warnings)

        self.status_var.set(f"执行完成：{summary.splitlines()[0]}")
        messagebox.showinfo("完成", f"拆分完成，{summary}")


def main() -> None:
    root = tk.Tk()
    app = FontSplitterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()