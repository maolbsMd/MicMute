"""鐢熸垚 MicMute.exe 鐨勫簲鐢ㄥ浘鏍?micmute.ico (鎵佸钩绠€绾﹂, 澶氬昂瀵?銆?
椋庢牸涓?micmute.py 涓?make_tray_icon 淇濇寔涓€鑷?
  鎵佸钩缁胯壊鍦嗗簳 + 椤堕儴鏌斿厜 + 绠€绾︾櫧鑹茬煝閲忛害鍏嬮銆?
鐩存帴杩愯涓€娆″嵆鍙? 涔嬪悗鎵撳寘浼氱敤 micmute.ico銆?"""
from PIL import Image, ImageDraw
from pathlib import Path

W = 256
SS = 4          # 瓒呴噰鏍峰€嶆暟, 淇濊瘉杈圭紭骞虫粦
S = W * SS


def draw_mic(d: ImageDraw.ImageDraw, cx: int, cy: int, scale: float, color):
    """缁樺埗绠€绾︾煝閲忛害鍏嬮 (鑳跺泭涓讳綋 + 鎵樻灦 + 绔嬫煴 + 搴曞骇)銆?""
    def P(x, y):
        return (cx + x * scale, cy + y * scale)

    # 鑳跺泭涓讳綋 (瀹炲績鍦嗚鐭╁舰)
    d.rounded_rectangle(
        [P(-6.5, -17), P(6.5, 8)],
        radius=6.5 * scale, fill=color)

    lw = max(1, int(2.6 * scale))
    # 鎵樻灦鍗婂渾寮?    bb = [P(-11, -10), P(11, 12)]
    d.arc([bb[0][0], bb[0][1], bb[1][0], bb[1][1]],
          start=0, end=180, fill=color, width=lw)
    # 绔嬫煴
    d.line([P(0, 11), P(0, 19)], fill=color, width=lw)
    # 搴曞骇
    d.line([P(-7.5, 19), P(7.5, 19)], fill=color, width=lw)


# 1) 閫忔槑鐢诲竷
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 2) 鎵佸钩鍦嗗簳 (绔栧悜娓愬彉: 椤?#40C078 -> 搴?#2EA463)
margin = int(10 * SS)
circle = Image.new("RGBA", (S, S), (0, 0, 0, 0))
grad = Image.new("RGBA", (S, S), (0, 0, 0, 0))
gd = ImageDraw.Draw(grad)
for y in range(S):
    t = y / S
    r = int(0x40 * (1 - t) + 0x2E * t)
    g = int(0xC0 * (1 - t) + 0xA4 * t)
    b = int(0x78 * (1 - t) + 0x63 * t)
    gd.line([(0, y), (S, y)], fill=(r, g, b, 255))

mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).ellipse([margin, margin, S - margin, S - margin], fill=255)
img.paste(grad, (0, 0), mask)

# 3) 椤堕儴鏌斿厜
hl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
hd = ImageDraw.Draw(hl)
hd.ellipse([margin + 6 * SS, margin, S - margin - 6 * SS, int(S * 0.55)],
           fill=(255, 255, 255, 70))
hl_masked = Image.new("RGBA", (S, S), (0, 0, 0, 0))
hl_masked.paste(hl, (0, 0), mask)
img.alpha_composite(hl_masked)

# 4) 绠€绾︾櫧鑹查害鍏嬮 (灞呬腑, 鐣ヤ笂绉?
cx, cy = S // 2, S // 2 - int(4 * SS)
mic_scale = 6.0 * SS
draw_mic(d, cx, cy, mic_scale, (255, 255, 255, 255))

# 5) 闄嶉噰鏍峰洖 256, 杈圭紭骞虫粦
img = img.resize((W, W), Image.LANCZOS)

# 6) 淇濆瓨涓哄灏哄 ICO
out = Path(__file__).parent / "micmute.ico"
img.save(out, format="ICO", sizes=[
    (16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)
])
print(f"宸茬敓鎴? {out}  ({out.stat().st_size / 1024:.1f} KB)")
