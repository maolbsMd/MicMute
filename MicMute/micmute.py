#!/usr/bin/env python3
"""MicMute - 绠€绾︿究鎼虹殑楹﹀厠椋庣鐞嗗伐鍏?(PyQt6 + Fluent UI)"""
from __future__ import annotations

import ctypes
import json
import subprocess
import os
import sys
import threading
import winsound
from pathlib import Path

APP_NAME    = "MicMute"
APP_VERSION = "2.0"

# ---------------------------------------------------------------------------
# 渚濊禆妫€鏌?# ---------------------------------------------------------------------------
def _check_deps():
    missing = []
    for mod, pkg in [
        ("PyQt6.QtCore",     "PyQt6"),
        ("PyQt6.QtGui",      "PyQt6"),
        ("PyQt6.QtWidgets",  "PyQt6"),
        ("qfluentwidgets",   "PyQt6-Fluent-Widgets"),
        ("pynput",           "pynput"),
        ("pycaw.pycaw",      "pycaw"),
    ]:
        try:
            __import__(mod)
        except ImportError:
            if pkg not in missing:
                missing.append(pkg)
    return missing

_missing = _check_deps()
if _missing:
    msg = f"[{APP_NAME}] 缂哄皯渚濊禆: {', '.join(_missing)}\npip install {' '.join(_missing)}"
    try:
        ctypes.windll.user32.MessageBoxW(0, msg, APP_NAME, 0x10)
    except Exception:
        print(msg, file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# 绗笁鏂?import
# ---------------------------------------------------------------------------
from PyQt6.QtCore import (
    Qt, QPoint, QTimer, QRectF, QPointF, pyqtSignal, QObject,
)
from PyQt6.QtGui import (
    QIcon, QFont, QColor, QPainter, QPen, QBrush, QPainterPath,
    QLinearGradient, QRadialGradient, QConicalGradient,
    QAction, QPixmap, QMouseEvent, QPaintEvent, QGuiApplication,
)
from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QWidget,
    QVBoxLayout, QHBoxLayout, QGraphicsDropShadowEffect, QButtonGroup,
    QLineEdit, QFrame,
)
from qfluentwidgets import (
    setTheme, Theme, setThemeColor,
    PrimaryPushButton, RadioButton, CheckBox,
    StrongBodyLabel, BodyLabel, TitleLabel, CaptionLabel, isDarkTheme,
)
from pynput import keyboard as kb
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume, IAudioMeterInformation
from pycaw.constants import CLSID_MMDeviceEnumerator, EDataFlow, DEVICE_STATE
from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
from comtypes import GUID, CLSCTX_ALL, CoCreateInstance

IID_IAudioEndpointVolume    = GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")
IID_IAudioMeterInformation  = GUID("{C02216F6-8C67-4B5B-9D00-D008E73E0064}")

# ---------------------------------------------------------------------------
# 鍗曞疄渚?# ---------------------------------------------------------------------------
_kernel32 = ctypes.windll.kernel32
_user32   = ctypes.windll.user32
_mutex = _kernel32.CreateMutexW(None, False, f"Global\\{APP_NAME}Tool")
if _kernel32.GetLastError() == 183:
    _user32.MessageBoxW(0, f"{APP_NAME} 宸插湪杩愯銆俓n璇锋鏌ョ郴缁熸墭鐩樸€?, APP_NAME, 0x40)
    sys.exit(0)

# ---------------------------------------------------------------------------
# 閰嶇疆
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                           else os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE_DIR, "micmute_settings.json")

DEFAULTS = {
    "mode":           "toggle",
    "toggle_hotkey":  "<ctrl>+<shift>+m",
    "ptt_hotkey":     "<mouse:x1>",
    "show_indicator": True,
    "indicator_x":    100,
    "indicator_y":    100,
    "indicator_size": 48,
    "indicator_locked": False,
    "auto_start":     False,
    "run_as_admin":   False,
    "theme":          "auto",
}

class Config:
    def __init__(self):
        self.data = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            merged = dict(DEFAULTS)
            merged.update({k: v for k, v in saved.items() if k in DEFAULTS})
            self.data = merged
        except Exception:
            self.data = dict(DEFAULTS)

    def save(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value):
        self.data[key] = value

config = Config()

# ---------------------------------------------------------------------------
# 闊抽鎺у埗
# ---------------------------------------------------------------------------
_com_tls = threading.local()

def _init_com():
    if not getattr(_com_tls, "ok", False):
        ctypes.windll.ole32.CoInitializeEx(0, 0)
        _com_tls.ok = True

class MicController:
    def __init__(self):
        self._muted    = False
        self._saved:   dict = {}
        self._ptt_held = None

    def _devices(self):
        _init_com()
        result = []
        try:
            enum = CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL)
            coll = enum.EnumAudioEndpoints(EDataFlow.eCapture.value, DEVICE_STATE.ACTIVE.value)
            for i in range(coll.GetCount()):
                dev = coll.Item(i)
                try:
                    act = dev.Activate(IID_IAudioEndpointVolume, CLSCTX_ALL, None)
                    vol = act.QueryInterface(IAudioEndpointVolume)
                    result.append((dev.GetId(), vol))
                except Exception:
                    pass
        except Exception:
            pass
        return result

    def mute(self, save=True):
        if save:
            self._saved.clear()
        for did, vol in self._devices():
            try:
                if save:
                    self._saved[did] = (vol.GetMute(), vol.GetMasterVolumeLevelScalar())
                vol.SetMute(True, None)
                vol.SetMasterVolumeLevelScalar(0.0, None)
            except Exception:
                pass
        self._muted = True

    def unmute(self, restore=True):
        for did, vol in self._devices():
            try:
                if restore and did in self._saved:
                    old_m, old_v = self._saved[did]
                    vol.SetMute(old_m, None)
                    vol.SetMasterVolumeLevelScalar(old_v, None)
                else:
                    vol.SetMute(False, None)
                    vol.SetMasterVolumeLevelScalar(1.0, None)
            except Exception:
                pass
        if restore:
            self._saved.clear()
        self._muted = False

    def toggle(self):
        if self._muted:
            self.unmute()
        else:
            self.mute()
        return self._muted

    def is_muted(self) -> bool:
        return self._muted

    def ptt_press(self):
        if self._ptt_held is not None:
            return
        self._ptt_held = self._muted
        if self._muted:
            self.unmute(restore=False)

    def ptt_release(self):
        if self._ptt_held is None:
            return
        was = self._ptt_held
        self._ptt_held = None
        if was:
            self.mute(save=False)

    def peak(self) -> float:
        _init_com()
        try:
            raw = AudioUtilities.GetMicrophone()
            if raw is None:
                return 0.0
            act   = raw.Activate(IID_IAudioMeterInformation, CLSCTX_ALL, None)
            meter = act.QueryInterface(IAudioMeterInformation)
            return meter.GetPeakValue()
        except Exception:
            return 0.0

mic = MicController()

# ---------------------------------------------------------------------------
# 澹伴煶鍙嶉
# ---------------------------------------------------------------------------
def _beep(muted: bool):
    freq = 600 if muted else 900
    threading.Thread(target=winsound.Beep, args=(freq, 120), daemon=True).start()

# 寮€鏈哄惎鍔?(schtasks 绠＄悊鍛樻潈闄? 鏇挎崲娉ㄥ唽琛ㄦ柟妗?
def _get_exe() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{os.path.abspath(__file__)}"'

def set_auto_start(enable: bool):
    try:
        if enable:
            subprocess.run(
                ["schtasks", "/create", "/tn", APP_NAME, "/tr", _get_exe(),
                 "/sc", "onlogon", "/rl", "highest", "/f", "/it"],
                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            subprocess.run(
                ["schtasks", "/delete", "/tn", APP_NAME, "/f"],
                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        pass

def get_auto_start() -> bool:
    try:
        r = subprocess.run(
            ["schtasks", "/query", "/tn", APP_NAME],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False

# 绠＄悊鍛樻潈闄?def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def relaunch_as_admin():
    try:
        if getattr(sys, "frozen", False):
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, "", None, 1)
        else:
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, f'"{os.path.abspath(__file__)}"', None, 1)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 蹇嵎閿鐞?(pynput 浣庣骇鍒敭鐩橀挬瀛? 鏀寔浠讳綍鍓嶅彴绐楀彛鍖呮嫭绠＄悊鍛樻潈闄?
# ---------------------------------------------------------------------------
# Windows 榧犳爣铏氭嫙閿爜 鈥?GetAsyncKeyState 杞姣?pynput 榧犳爣閽╁瓙鏇村彲闈?_MOUSE_VK = {
    "x1":     0x05,  # VK_XBUTTON1
    "x2":     0x06,  # VK_XBUTTON2
    "middle": 0x04,  # VK_MBUTTON
    "left":   0x01,  # VK_LBUTTON
    "right":  0x02,  # VK_RBUTTON
}
_GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState
_GetAsyncKeyState.restype = ctypes.c_short


class HotkeyManager(QObject):
    _sig_toggle = pyqtSignal()
    _sig_ptt_on = pyqtSignal()
    _sig_ptt_off = pyqtSignal()

    def __init__(self, on_toggle, on_ptt_on, on_ptt_off):
        super().__init__()
        self._on_toggle  = on_toggle
        self._on_ptt_on  = on_ptt_on
        self._on_ptt_off = on_ptt_off
        self._sig_toggle.connect(on_toggle)
        self._sig_ptt_on.connect(on_ptt_on)
        self._sig_ptt_off.connect(on_ptt_off)
        self._mouse_timer = None
        self._mouse_vk    = 0
        self._mouse_is_ptt = False
        self._mouse_was_down = False
        self._kb_listener    = None

    def stop(self):
        if self._mouse_timer is not None:
            self._mouse_timer.stop()
            self._mouse_timer.deleteLater()
            self._mouse_timer = None
        if self._kb_listener is not None:
            try:
                self._kb_listener.stop()
            except Exception:
                pass
        self._kb_listener = None

    def restart(self):
        self.stop()
        self.start()

    def start(self):
        mode      = config.get("mode")
        toggle_hk = config.get("toggle_hotkey") or ""
        ptt_hk    = config.get("ptt_hotkey")    or ""

        if mode == "toggle":
            if toggle_hk.startswith("<mouse:"):
                self._start_mouse(toggle_hk.replace("<mouse:", "").rstrip(">"), is_ptt=False)
            elif toggle_hk:
                self._start_kb_toggle(toggle_hk)
        else:
            if ptt_hk.startswith("<mouse:"):
                self._start_mouse(ptt_hk.replace("<mouse:", "").rstrip(">"), is_ptt=True)
            elif ptt_hk:
                self._start_kb_ptt(ptt_hk)

    # ---- 閿洏 toggle --------------------------------------------------------
    def _start_kb_toggle(self, spec: str):
        """閿洏浣庣骇鍒挬瀛? 缁勫悎閿寜涓嬫椂瑙﹀彂涓€娆?toggle"""
        try:
            combo = set(kb.HotKey.parse(spec))
        except Exception:
            return
        pressed: set = set()
        fired  = [False]

        def on_press(key):
            try:
                pressed.add(kb.HotKey._normalize(key))
            except Exception:
                return
            if not fired[0] and combo.issubset(pressed):
                fired[0] = True
                self._sig_toggle.emit()

        def on_release(key):
            try:
                pressed.discard(kb.HotKey._normalize(key))
            except Exception:
                pass
            if not combo.issubset(pressed):
                fired[0] = False

        self._kb_listener = kb.Listener(on_press=on_press, on_release=on_release)
        self._kb_listener.start()

    # ---- 閿洏 PTT -----------------------------------------------------------
    def _start_kb_ptt(self, spec: str):
        try:
            combo = set(kb.HotKey.parse(spec))
        except Exception:
            return
        pressed: set = set()
        active  = [False]

        def on_press(key):
            try:
                pressed.add(kb.HotKey._normalize(key))
            except Exception:
                return
            if not active[0] and combo.issubset(pressed):
                active[0] = True
                self._sig_ptt_on.emit()

        def on_release(key):
            k = kb.HotKey._normalize(key)
            if active[0] and k in combo:
                active[0] = False
                self._sig_ptt_off.emit()
            pressed.discard(k)

        self._kb_listener = kb.Listener(on_press=on_press, on_release=on_release)
        self._kb_listener.start()

    # ---- 榧犳爣 (GetAsyncKeyState 杞, 姣?pynput 閽╁瓙鏇村彲闈? -----------
    def _start_mouse(self, btn_name: str, is_ptt: bool):
        vk = _MOUSE_VK.get(btn_name)
        if vk is None:
            return
        self._mouse_vk = vk
        self._mouse_is_ptt = is_ptt
        self._mouse_was_down = False

        def poll():
            down = (_GetAsyncKeyState(self._mouse_vk) & 0x8000) != 0
            if down and not self._mouse_was_down:
                self._mouse_was_down = True
                if self._mouse_is_ptt:
                    self._sig_ptt_on.emit()
                else:
                    self._sig_toggle.emit()
            elif not down and self._mouse_was_down:
                self._mouse_was_down = False
                if self._mouse_is_ptt:
                    self._sig_ptt_off.emit()

        self._mouse_timer = QTimer(self)
        self._mouse_timer.timeout.connect(poll)
        self._mouse_timer.start(50)  # 50ms 杞

# ---------------------------------------------------------------------------
# 鐭㈤噺楹﹀厠椋庣粯鍒?# ---------------------------------------------------------------------------
def _capsule() -> QPainterPath:
    p = QPainterPath()
    p.addRoundedRect(QRectF(-6.5, -17, 13, 25), 6.5, 6.5)
    return p

def _stand() -> QPainterPath:
    p = QPainterPath()
    p.moveTo(-11, 1)
    p.arcTo(QRectF(-11, -10, 22, 22), 180, -180)
    p.moveTo(0, 11);  p.lineTo(0, 19)
    p.moveTo(-7.5, 19); p.lineTo(7.5, 19)
    return p

def paint_mic(painter: QPainter, cx: float, cy: float, size: float,
              color: QColor, slash: bool = False):
    painter.save()
    painter.translate(cx, cy)
    painter.scale(size / 32.0, size / 32.0)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawPath(_capsule())
    pen = QPen(color, 2.6, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(_stand())
    if slash:
        painter.setPen(QPen(color, 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(-13, -13), QPointF(13, 13))
    painter.restore()

def make_tray_icon(muted: bool) -> QIcon:
    px = QPixmap(64, 64)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    c1, c2 = (QColor(235, 87, 87), QColor(214, 64, 64)) if muted \
             else (QColor(64, 192, 120), QColor(46, 164, 99))
    g = QLinearGradient(0, 4, 0, 60)
    g.setColorAt(0, c1); g.setColorAt(1, c2)
    p.setBrush(QBrush(g)); p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(3, 3, 58, 58)
    hl = QLinearGradient(0, 4, 0, 38)
    hl.setColorAt(0, QColor(255, 255, 255, 70)); hl.setColorAt(1, QColor(255, 255, 255, 0))
    p.setBrush(QBrush(hl)); p.drawEllipse(3, 3, 58, 58)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(0, 0, 0, 28), 1)); p.drawEllipse(3, 3, 58, 58)
    paint_mic(p, 32, 31, 30, QColor(255, 255, 255), slash=muted)
    p.end()
    return QIcon(px)

# ---------------------------------------------------------------------------
# 娴姩鎸囩ず鍣?# ---------------------------------------------------------------------------
class FloatIndicator(QWidget):
    toggled          = pyqtSignal()
    settingsRequested = pyqtSignal()
    hideRequested    = pyqtSignal()
    quitRequested    = pyqtSignal()
    lockRequested    = pyqtSignal()

    @property
    def SIZE(self) -> int:
        return int(config.get("indicator_size", 96))

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._apply_size()

        # 涓嶄娇鐢?QGraphicsDropShadowEffect锛堜笌 TranslucentBackground 鍦ㄩ儴鍒?Windows 涓嬪啿绐侊級
        self._drag_pos = None
        self._state    = "on"   # "on" | "mute" | "talking"
        self._level    = 0.0
        self._ptt      = False
        self._locked   = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(80)

    def showEvent(self, event):
        super().showEvent(event)
        try:
            hwnd = int(self.winId())
            ctypes.windll.user32.SetWindowPos(hwnd, 0xFFFFFFFF, 0, 0, 0, 0, 0x0002|0x0001)
        except Exception:
            pass

    def _apply_size(self):
        self.setFixedSize(self.SIZE, self.SIZE)

    # 渚涘閮ㄧ洿鎺ヨ皟鐢?    def set_state(self, muted: bool, ptt: bool = False):
        self._ptt = ptt
        self._state = "mute" if muted else ("talking" if ptt else "on")
        self._level = 0.0 if muted else self._level
        self.update()

    def _poll(self):
        try:
            muted = mic.is_muted()
            self._level = 0.0 if muted else mic.peak()
            self._state = "mute" if muted else ("talking" if self._ptt and self._level > 0.05 else "on")
            self.update()
        except Exception:
            pass

    def set_locked(self, locked: bool):
        self._locked = locked
        self._set_click_through(locked)
        self.update()

    def _set_click_through(self, enable: bool):
        try:
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if enable:
                style |= WS_EX_TRANSPARENT
            else:
                style &= ~WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def mousePressEvent(self, e: QMouseEvent):
        if self._locked:
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._drag_pos and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            config.set("indicator_x", self.x())
            config.set("indicator_y", self.y())

    def mouseDoubleClickEvent(self, e: QMouseEvent):
        if self._locked:
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self.toggled.emit()

    def contextMenuEvent(self, e):
        if self._locked:
            return
        menu = QMenu(self)
        a_tog  = menu.addAction("鍙栨秷闈欓煶" if mic.is_muted() else "闈欓煶楹﹀厠椋?)
        a_set  = menu.addAction("璁剧疆鈥?)
        menu.addSeparator()
        a_lock = menu.addAction("閿佸畾鎸囩ず鍣?)
        a_lock.triggered.connect(self.lockRequested.emit)
        menu.addSeparator()
        a_hide = menu.addAction("闅愯棌鎸囩ず鍣?)
        menu.addSeparator()
        a_quit = menu.addAction("閫€鍑?)
        act = menu.exec(e.globalPos())
        if act == a_tog:  self.toggled.emit()
        elif act == a_set:  self.settingsRequested.emit()
        elif act == a_hide: self.hideRequested.emit()
        elif act == a_quit: self.quitRequested.emit()

    def paintEvent(self, e: QPaintEvent):
        s = self.SIZE
        r = s / 2.0
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # 涓夎璺緞
        tri = QPainterPath()
        h = r * 0.85
        y0 = r - h * 0.55
        tri.moveTo(r, y0 - h)
        tri.lineTo(r - h * 0.9, y0 + h * 0.5)
        tri.lineTo(r + h * 0.9, y0 + h * 0.5)
        tri.closeSubpath()

        muted = self._state == "mute"
        locked = self._locked

        # 閿佸畾鏃舵洿閫忔槑
        bg_alpha = 120 if locked else 190
        if muted:
            bg = QColor(25, 20, 20, bg_alpha)
        else:
            bg = QColor(18, 18, 22, bg_alpha)

        # 杞槾褰?(閿佸畾鏃舵棤闃村奖)
        if not locked:
            for i in range(3, 0, -1):
                p.setBrush(QColor(0, 0, 0, 8 - i * 1))
                p.setPen(Qt.PenStyle.NoPen)
                p.translate(0, i * 1.5)
                p.drawPath(tri)
                p.translate(0, -i * 1.5)

        # 鑳屾櫙
        p.setBrush(bg); p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(tri)

        # 寰珮鍏?(閿佸畾鏃朵笉鐢?
        if not locked:
            hl = QPainterPath()
            hl.moveTo(r, y0 - h)
            hl.lineTo(r - h * 0.45, y0 - h * 0.35)
            hl.lineTo(r + h * 0.45, y0 - h * 0.35)
            hl.closeSubpath()
            p.setBrush(QColor(255, 255, 255, 30))
            p.drawPath(hl)

        # 闊抽噺鐜?(閿佸畾鏃朵篃淇濈暀)
        if not muted and self._level > 0.01:
            perim = 5.4 * h
            lvl = min(1.0, self._level * 4)
            dp = [perim * lvl, perim * (1 - lvl)]
            ring_pen = QPen(QColor(255, 255, 255, 190), 2.5,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            ring_pen.setDashPattern(dp)
            p.setPen(ring_pen); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(tri)

        # 閿佸畾鏃? 鍙敾灏忓渾鐐? 涓嶇敾鏂囧瓧/灏忎笁瑙?        if locked:
            dot_color = QColor(255, 170, 170, 140) if muted else QColor(255, 255, 255, 120)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(dot_color)
            p.drawEllipse(QPointF(r, r), s * 0.07, s * 0.07)
            p.end()
            return

        # 鏂囧瓧/鍥炬爣棰滆壊 (闈欓煶鏃舵瀬娣＄矇)
        accent = QColor(255, 160, 160) if muted else QColor(255, 255, 255)
        label  = "MUTE" if muted else ("TALK" if self._state == "talking" else "ON")

        # 鎻忚竟 (闈欓煶鏃舵瀬娣?
        if muted:
            p.setPen(QPen(QColor(255, 160, 160, 60), 1.2))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 50), 0.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(tri)

        # 涓棿灏忎笁瑙?        tiny_r = s * 0.08
        tiny = QPainterPath()
        y1 = r - s * 0.02
        tiny.moveTo(r, y1 - tiny_r * 1.5)
        tiny.lineTo(r - tiny_r * 1.3, y1 + tiny_r * 0.6)
        tiny.lineTo(r + tiny_r * 1.3, y1 + tiny_r * 0.6)
        tiny.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawPath(tiny)

        # 鐘舵€佹枃瀛?        font = QFont("Microsoft YaHei UI", max(6, int(s * 0.13)))
        font.setBold(True)
        p.setFont(font); p.setPen(QPen(accent))
        p.drawText(QRectF(0, r + s * 0.07, s, s * 0.25), Qt.AlignmentFlag.AlignCenter, label)
        p.end()

# ---------------------------------------------------------------------------
# 璁剧疆绐楀彛
# ---------------------------------------------------------------------------
class SettingsWindow(QWidget):
    saved = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} 璁剧疆")
        self.setWindowIcon(make_tray_icon(False))
        self.resize(450, 560)
        self.setMinimumSize(420, 520)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(0)

        sub_style = ("color:rgba(0,0,0,.5);" if not isDarkTheme()
                     else "color:rgba(255,255,255,.5);")
        hint_style = ("color:rgba(0,0,0,.4);" if not isDarkTheme()
                      else "color:rgba(255,255,255,.4);")

        title = TitleLabel(f"{APP_NAME} 璁剧疆")
        root.addWidget(title); root.addSpacing(4)
        sub = CaptionLabel("蹇嵎閿?路 宸ヤ綔妯″紡 路 澶栬")
        sub.setStyleSheet(sub_style)
        root.addWidget(sub); root.addSpacing(18)

        # === 宸ヤ綔妯″紡 ======================================================
        root.addWidget(StrongBodyLabel("宸ヤ綔妯″紡"))
        self._mg = QButtonGroup(self)
        self._rb_tog = RadioButton("鍒囨崲闈欓煶   鎸変竴涓嬪垏鎹㈠紑/鍏?)
        self._rb_ptt = RadioButton("鎸変綇璇磋瘽   鎸変綇鏃朵复鏃跺彇娑堥潤闊?)
        self._mg.addButton(self._rb_tog, 0)
        self._mg.addButton(self._rb_ptt, 1)
        (self._rb_ptt if config.get("mode") == "ptt" else self._rb_tog).setChecked(True)
        root.addSpacing(6)
        root.addWidget(self._rb_tog); root.addWidget(self._rb_ptt)
        root.addSpacing(16)

        # 鍒嗛殧
        sep1 = QFrame(); sep1.setFrameShape(QFrame.Shape.HLine); sep1.setStyleSheet("background:rgba(128,128,128,40)")
        root.addWidget(sep1); root.addSpacing(14)

        # === 蹇嵎閿?========================================================
        root.addWidget(StrongBodyLabel("蹇嵎閿?))
        root.addSpacing(8)
        root.addWidget(BodyLabel("鍒囨崲蹇嵎閿?))
        root.addSpacing(4)
        self._ed_tog = QLineEdit(config.get("toggle_hotkey") or "")
        self._ed_tog.setPlaceholderText("渚嬪 ctrl+shift+m")
        self._ed_tog.setFixedHeight(36)
        root.addWidget(self._ed_tog)
        root.addSpacing(12)
        root.addWidget(BodyLabel("鎸変綇璇磋瘽閿?))
        root.addSpacing(4)
        self._ed_ptt = QLineEdit(config.get("ptt_hotkey") or "")
        self._ed_ptt.setPlaceholderText("渚嬪 ctrl+alt+space  鎴? <mouse:x2>")
        self._ed_ptt.setFixedHeight(36)
        root.addWidget(self._ed_ptt)
        root.addSpacing(4)
        hint = CaptionLabel("鏍煎紡: ctrl+shift+m / alt+f4 / <mouse:x1> 绛?)
        hint.setStyleSheet(hint_style)
        root.addWidget(hint); root.addSpacing(16)

        # 鍒嗛殧
        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine); sep2.setStyleSheet("background:rgba(128,128,128,40)")
        root.addWidget(sep2); root.addSpacing(14)

        # === 澶栬 ===========================================================
        root.addWidget(StrongBodyLabel("澶栬"))
        root.addSpacing(8)
        self._cb_show = CheckBox("鏄剧ず娴姩鎸囩ず鍣?)
        self._cb_show.setChecked(bool(config.get("show_indicator")))
        root.addWidget(self._cb_show)
        root.addSpacing(10)

        root.addWidget(BodyLabel("鎸囩ず鍣ㄥぇ灏?))
        root.addSpacing(4)
        sz_row = QHBoxLayout(); sz_row.setSpacing(12)
        self._sg = QButtonGroup(self)
        cur_sz = config.get("indicator_size", 48)
        for lbl, val in [("灏?, 48), ("涓?, 64), ("澶?, 80)]:
            rb = RadioButton(lbl)
            rb.setProperty("v", val)
            if val == cur_sz:
                rb.setChecked(True)
            self._sg.addButton(rb)
            sz_row.addWidget(rb)
        sz_row.addStretch(1)
        root.addLayout(sz_row); root.addSpacing(4)
        sz_hint = CaptionLabel("娴姩鎸囩ず鍣ㄥ彲鎷栧姩锛屼綅缃細鑷姩璁板繂")
        sz_hint.setStyleSheet(hint_style)
        root.addWidget(sz_hint); root.addSpacing(10)

        self._cb_autostart = CheckBox("寮€鏈鸿嚜鍔ㄥ惎鍔?)
        self._cb_autostart.setChecked(get_auto_start())
        root.addWidget(self._cb_autostart)
        root.addSpacing(8)
        self._cb_admin = CheckBox("绠＄悊鍛樺惎鍔?)
        self._cb_admin.setChecked(config.get("run_as_admin", False))
        root.addWidget(self._cb_admin)
        root.addStretch(1)

        # === 鎸夐挳 ===========================================================
        br = QHBoxLayout(); br.setSpacing(12)
        btn_cancel = PrimaryPushButton("鍏抽棴")
        btn_cancel.setFixedHeight(40); btn_cancel.clicked.connect(self.close)
        btn_save   = PrimaryPushButton("淇濆瓨骞跺簲鐢?)
        btn_save.setFixedHeight(40); btn_save.clicked.connect(self._save)
        br.addStretch(1); br.addWidget(btn_cancel); br.addWidget(btn_save)
        root.addLayout(br)

    def _save(self):
        config.set("mode", "ptt" if self._rb_ptt.isChecked() else "toggle")
        config.set("show_indicator", self._cb_show.isChecked())
        def norm_hk(text: str) -> str:
            t = text.strip().lower()
            parts = [p.strip() for p in t.split("+")]
            result = []
            for p in parts:
                if p in ("ctrl", "shift", "alt", "cmd"):
                    result.append(f"<{p}>")
                else:
                    result.append(p)
            return "+".join(result) if result else ""
        tog = self._ed_tog.text().strip()
        ptt = self._ed_ptt.text().strip()
        if tog:
            config.set("toggle_hotkey", norm_hk(tog) if not tog.startswith("<mouse:") else tog)
        if ptt:
            config.set("ptt_hotkey", norm_hk(ptt) if not ptt.startswith("<mouse:") else ptt)
        for b in self._sg.buttons():
            if b.isChecked():
                config.set("indicator_size", b.property("v"))
                break
        set_auto_start(self._cb_autostart.isChecked())
        config.set("run_as_admin", self._cb_admin.isChecked())
        config.save()
        self.saved.emit()
        self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()

# ---------------------------------------------------------------------------
# 涓诲簲鐢?# ---------------------------------------------------------------------------
class App:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setFont(QFont("Microsoft YaHei UI", 9))

        tm = {"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}
        setTheme(tm.get(config.get("theme", "auto"), Theme.AUTO))
        setThemeColor("#0078D4")

        self._ptt      = False
        self._settings = None

        # 鎸囩ず鍣?        self.ind = FloatIndicator()
        if config.get("indicator_locked", False):
            self.ind.set_locked(True)
        self.ind.toggled.connect(self._do_toggle)
        self.ind.settingsRequested.connect(self.open_settings)
        self.ind.hideRequested.connect(self._hide_ind)
        self.ind.lockRequested.connect(self._toggle_lock)
        self.ind.quitRequested.connect(self.shutdown)

        # 鐑敭 (蹇呴』鍦?QApplication 瀛樺湪鍚庡垱寤?
        self.hk = HotkeyManager(
            on_toggle  = self._do_toggle,
            on_ptt_on  = self._ptt_on,
            on_ptt_off = self._ptt_off,
        )

        # PTT 妯″紡鍚姩鏃堕粯璁ら潤闊?        if config.get("mode") == "ptt":
            mic.mute()

        # 鎵樼洏
        self.tray = QSystemTrayIcon(make_tray_icon(mic.is_muted()))
        self.tray.setToolTip(APP_NAME)
        self._build_tray()
        self.tray.activated.connect(self._tray_click)
        self.tray.show()

        # 鍚姩
        self.hk.start()
        self._apply_vis()
        self._place_ind()

    # ---- 鏍稿績鎿嶄綔 ----------------------------------------------------------
    def _do_toggle(self):
        mic.toggle()
        self._sync(sound=True)

    def _ptt_on(self):
        self._ptt = True
        mic.ptt_press()
        self._sync(sound=False)

    def _ptt_off(self):
        self._ptt = False
        mic.ptt_release()
        self._sync(sound=False)

    def _sync(self, sound=False):
        muted = mic.is_muted()
        self.tray.setIcon(make_tray_icon(muted))
        self.tray.setToolTip(f"{APP_NAME} 鈥?{'宸查潤闊? if muted else '宸插紑鍚?}")
        if hasattr(self, "act_state"):
            self.act_state.setText("楹﹀厠椋庯細宸查潤闊? if muted else "楹﹀厠椋庯細宸插紑鍚?)
        self.ind.set_state(muted, self._ptt)
        if sound:
            _beep(muted)

    # ---- 鎸囩ず鍣?------------------------------------------------------------
    def _apply_vis(self):
        (self.ind.show if config.get("show_indicator") else self.ind.hide)()

    def _place_ind(self):
        x, y  = config.get("indicator_x", 100), config.get("indicator_y", 100)
        scr   = QGuiApplication.primaryScreen().availableGeometry()
        x     = max(0, min(x, scr.width()  - self.ind.SIZE))
        y     = max(0, min(y, scr.height() - self.ind.SIZE))
        self.ind.move(x, y)

    def _hide_ind(self):
        config.set("show_indicator", False)
        config.save()
        self.ind.hide()
        self._build_tray()

    def _show_ind(self):
        config.set("show_indicator", True)
        config.save()
        self.ind.show()
        self.ind.raise_()
        # Win32 寮哄埗缃《
        try:
            hwnd = int(self.ind.winId())
            ctypes.windll.user32.SetWindowPos(hwnd, 0xFFFFFFFF, 0, 0, 0, 0, 0x0002|0x0001)
        except Exception:
            pass
        self._build_tray()

    # ---- 鎵樼洏 --------------------------------------------------------------
    def _build_tray(self):
        m = QMenu()
        muted = mic.is_muted()
        self.act_state = QAction("楹﹀厠椋庯細宸查潤闊? if muted else "楹﹀厠椋庯細宸插紑鍚?, m)
        self.act_state.triggered.connect(self._do_toggle)
        m.addAction(self.act_state)
        m.addSeparator()
        # 鍒囨崲妯″紡
        mode = config.get("mode")
        act_mode = QAction("鍒囨崲鍒版寜閿紑楹︽ā寮? if mode == "toggle" else "鍒囨崲鍒板垏鎹㈡ā寮?, m)
        act_mode.triggered.connect(self._toggle_mode)
        m.addAction(act_mode)
        m.addSeparator()
        a = QAction("璁剧疆鈥?, m); a.triggered.connect(self.open_settings); m.addAction(a)
        show = config.get("show_indicator")
        a2 = QAction("闅愯棌娴姩鎸囩ず鍣? if show else "鏄剧ず娴姩鎸囩ず鍣?, m)
        a2.triggered.connect(self._hide_ind if show else self._show_ind)
        m.addAction(a2)
        self.act_lock = QAction("閿佸畾鎸囩ず鍣? if not self.ind._locked else "瑙ｉ攣鎸囩ず鍣?, m)
        self.act_lock.triggered.connect(self._toggle_lock)
        m.addAction(self.act_lock)
        m.addSeparator()
        a3 = QAction("閫€鍑?, m); a3.triggered.connect(self.shutdown); m.addAction(a3)
        self.tray.setContextMenu(m)

    def _toggle_mode(self):
        new_mode = "ptt" if config.get("mode") == "toggle" else "toggle"
        config.set("mode", new_mode)
        config.save()
        if new_mode == "ptt" and not mic.is_muted():
            mic.mute()
        elif new_mode == "toggle" and mic.is_muted():
            mic.unmute()
        self.hk.restart()
        self._sync()
        self._build_tray()

    def _toggle_lock(self):
        self.ind.set_locked(not self.ind._locked)
        config.set("indicator_locked", self.ind._locked)
        config.save()
        self._build_tray()

    def _tray_click(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._do_toggle()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_settings()

    # ---- 璁剧疆绐楀彛 ----------------------------------------------------------
    def open_settings(self):
        if self._settings and self._settings.isVisible():
            self._settings.raise_(); self._settings.activateWindow(); return
        w = SettingsWindow()
        w.saved.connect(self._on_saved)
        self._settings = w
        w.show(); w.raise_(); w.activateWindow()

    def _on_saved(self):
        self.ind._apply_size()
        self._apply_vis()
        self._place_ind()
        self.hk.restart()
        self._sync()
        self._build_tray()

    # ---- 鐢熷懡鍛ㄦ湡 ----------------------------------------------------------
    def shutdown(self):
        self.hk.stop()
        # 閫€鍑烘椂鏃犳潯浠跺己鍒舵仮澶嶆墍鏈夐害鍏嬮锛屼笉渚濊禆鍐呴儴鐘舵€?        try:
            for _, vol in mic._devices():
                try:
                    vol.SetMute(False, None)
                    vol.SetMasterVolumeLevelScalar(1.0, None)
                except Exception:
                    pass
        except Exception:
            pass
        config.save()
        try:
            self.tray.hide()
        except Exception:
            pass
        self.ind.close()
        self.app.quit()

    def run(self):
        return self.app.exec()

# ---------------------------------------------------------------------------
def main():
    if config.get("run_as_admin", False) and not is_admin():
        _kernel32.CloseHandle(_mutex)
        relaunch_as_admin()
        sys.exit(0)
    app = App()
    sys.exit(app.run())

if __name__ == "__main__":
    main()
