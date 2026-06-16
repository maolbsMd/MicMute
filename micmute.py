#!/usr/bin/env python3
"""MicMute - 简约便携的麦克风管理工具 (PyQt6 + Fluent UI)"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import sys
import threading
import winreg
import winsound
from pathlib import Path

APP_NAME    = "MicMute"
APP_VERSION = "2.0"

# ---------------------------------------------------------------------------
# 依赖检查
# ---------------------------------------------------------------------------
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
    msg = f"[{APP_NAME}] 缺少依赖: {', '.join(_missing)}\npip install {' '.join(_missing)}"
    try:
        ctypes.windll.user32.MessageBoxW(0, msg, APP_NAME, 0x10)
    except Exception:
        print(msg, file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# 第三方 import
# ---------------------------------------------------------------------------
from PyQt6.QtCore import (
    Qt, QPoint, QTimer, QRectF, QPointF, pyqtSignal, QAbstractNativeEventFilter,
)
from PyQt6.QtGui import (
    QIcon, QFont, QColor, QPainter, QPen, QBrush, QPainterPath,
    QLinearGradient, QRadialGradient, QConicalGradient,
    QAction, QPixmap, QMouseEvent, QPaintEvent, QGuiApplication,
)
from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QWidget,
    QVBoxLayout, QHBoxLayout, QGraphicsDropShadowEffect, QButtonGroup,
    QLineEdit,
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
# 单实例
# ---------------------------------------------------------------------------
_kernel32 = ctypes.windll.kernel32
_user32   = ctypes.windll.user32
_mutex = _kernel32.CreateMutexW(None, False, f"Global\\{APP_NAME}Tool")
if _kernel32.GetLastError() == 183:
    _user32.MessageBoxW(0, f"{APP_NAME} 已在运行。\n请检查系统托盘。", APP_NAME, 0x40)
    sys.exit(0)

# ---------------------------------------------------------------------------
# 配置
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
    "auto_start":     False,
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
# 音频控制
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
# 声音反馈
# ---------------------------------------------------------------------------
def _beep(muted: bool):
    freq = 600 if muted else 900
    threading.Thread(target=winsound.Beep, args=(freq, 120), daemon=True).start()

# 开机启动
def _get_startup_key():
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)

def set_auto_start(enable: bool):
    try:
        key = _get_startup_key()
        if enable:
            exe = sys.executable if not getattr(sys, "frozen", False) else sys.executable
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe)
        else:
            winreg.DeleteValue(key, APP_NAME)
        winreg.CloseKey(key)
    except Exception:
        pass

def get_auto_start() -> bool:
    try:
        key = _get_startup_key()
        try:
            winreg.QueryValueEx(key, APP_NAME)
            winreg.CloseKey(key)
            return True
        except Exception:
            winreg.CloseKey(key)
            return False
    except Exception:
        return False

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def relaunch_as_admin():
    try:
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Win32 热键解析
# ---------------------------------------------------------------------------
# Win32 鼠标底层钩子常量
WH_MOUSE_LL    = 14
WM_LBUTTONDOWN = 0x0201; WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204; WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207; WM_MBUTTONUP = 0x0208
WM_XBUTTONDOWN = 0x020B; WM_XBUTTONUP = 0x020C
XBUTTON1       = 0x0001; XBUTTON2 = 0x0002

_MOUSE_DOWN = {"x1": WM_XBUTTONDOWN, "x2": WM_XBUTTONDOWN,
               "left": WM_LBUTTONDOWN, "right": WM_RBUTTONDOWN,
               "middle": WM_MBUTTONDOWN}
_MOUSE_UP   = {"x1": WM_XBUTTONUP,   "x2": WM_XBUTTONUP,
               "left": WM_LBUTTONUP,   "right": WM_RBUTTONUP,
               "middle": WM_MBUTTONUP}
_MOUSE_XID  = {"x1": XBUTTON1, "x2": XBUTTON2}

class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt",          _Point),
        ("mouseData",   ctypes.wintypes.DWORD),
        ("flags",       ctypes.wintypes.DWORD),
        ("time",        ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

_HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int,
                                ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)
_VK = {
    **{c: 0x41 + i for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")},
    **{str(i): 0x30 + i for i in range(10)},
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "backspace": 0x08,
    "escape": 0x1B, "insert": 0x2D, "delete": 0x2E,
    "home": 0x24, "end": 0x23, "page_up": 0x21, "page_down": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
}
_MOD = {"<ctrl>": 0x0002, "<shift>": 0x0004, "<alt>": 0x0001, "<cmd>": 0x0008}
_NOREPEAT = 0x4000

def _parse_hk(spec: str):
    """'<ctrl>+<shift>+m' -> (mod, vk) 或 None"""
    mod, vk = _NOREPEAT, None
    for p in spec.lower().split("+"):
        p = p.strip()
        if p in _MOD:
            mod |= _MOD[p]
        elif p.startswith("<") and p.endswith(">"):
            vk = _VK.get(p[1:-1])
        else:
            vk = _VK.get(p)
    return (mod, vk) if vk else None

# ---------------------------------------------------------------------------
# WM_HOTKEY 过滤器 (在 Qt 事件循环内截获)
# ---------------------------------------------------------------------------
WM_HOTKEY = 0x0312
HK_TOGGLE = 1
HK_PTT    = 2

class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self._cb = callback

    def nativeEventFilter(self, event_type, message):
        # message 是指向 MSG 结构体的指针
        try:
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self._cb(msg.wParam)
        except Exception:
            pass
        return False, 0

# ---------------------------------------------------------------------------
# 快捷键管理
# ---------------------------------------------------------------------------
class HotkeyManager:
    def __init__(self, on_toggle, on_ptt_on, on_ptt_off):
        self._on_toggle  = on_toggle
        self._on_ptt_on  = on_ptt_on
        self._on_ptt_off = on_ptt_off
        self._mouse_hook    = None
        self._mouse_hook_cb = None
        self._mouse_thread  = None
        self._mouse_stop    = None
        self._kb_listener   = None
        self._registered: list[int] = []
        self._filter = _HotkeyFilter(self._on_win32_hotkey)
        QApplication.instance().installNativeEventFilter(self._filter)

    # ---- Win32 热键 --------------------------------------------------------
    def _reg(self, hid: int, spec: str) -> bool:
        parsed = _parse_hk(spec)
        if not parsed:
            return False
        mod, vk = parsed
        _user32.UnregisterHotKey(None, hid)
        ok = bool(_user32.RegisterHotKey(None, hid, mod, vk))
        if ok:
            self._registered.append(hid)
        return ok

    def _unreg_all(self):
        for hid in self._registered:
            _user32.UnregisterHotKey(None, hid)
        self._registered.clear()

    def _on_win32_hotkey(self, hid: int):
        if hid == HK_TOGGLE:
            self._on_toggle()
        elif hid == HK_PTT:
            self._on_ptt_on()

    # ---- 鼠标 (WH_MOUSE_LL 底层钩子, 全球最可靠) -------------------------
    def _start_mouse(self, btn_name: str, is_ptt: bool):
        down_msg = _MOUSE_DOWN.get(btn_name)
        up_msg   = _MOUSE_UP.get(btn_name)
        xid      = _MOUSE_XID.get(btn_name)
        if down_msg is None:
            return

        self._mouse_is_ptt = is_ptt
        self._mouse_stop   = threading.Event()

        def hook_proc(nCode, wParam, lParam):
            if nCode >= 0:
                if wParam == down_msg:
                    if xid is not None:
                        ms = ctypes.cast(lParam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
                        if (ms.mouseData >> 16) != xid:
                            return _user32.CallNextHookEx(None, nCode, wParam, lParam)
                    if is_ptt:
                        QTimer.singleShot(0, self._on_ptt_on)
                    else:
                        QTimer.singleShot(0, self._on_toggle)
                elif wParam == up_msg:
                    if xid is not None:
                        ms = ctypes.cast(lParam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
                        if (ms.mouseData >> 16) != xid:
                            return _user32.CallNextHookEx(None, nCode, wParam, lParam)
                    if is_ptt:
                        QTimer.singleShot(0, self._on_ptt_off)
            return _user32.CallNextHookEx(None, nCode, wParam, lParam)

        self._mouse_hook_cb = _HOOKPROC(hook_proc)

        def _hook_thread():
            hmod = ctypes.windll.kernel32.GetModuleHandleW(None)
            self._mouse_hook = _user32.SetWindowsHookExW(
                WH_MOUSE_LL, self._mouse_hook_cb, hmod, 0)
            tid = ctypes.windll.kernel32.GetCurrentThreadId()
            msg  = ctypes.wintypes.MSG()
            while not self._mouse_stop.is_set():
                while _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    if msg.message == 0x0012:  # WM_QUIT
                        break
                    _user32.TranslateMessage(ctypes.byref(msg))
                    _user32.DispatchMessageW(ctypes.byref(msg))
                self._mouse_stop.wait(0.05)
            _user32.UnhookWindowsHookEx(self._mouse_hook)
            self._mouse_hook = None

        self._mouse_thread = threading.Thread(target=_hook_thread, daemon=True)
        self._mouse_thread.start()

    # ---- pynput 键盘 PTT ---------------------------------------------------
    def _start_kb_ptt(self, spec: str):
        try:
            combo = set(kb.HotKey.parse(spec))
        except Exception:
            return
        pressed: set = set()
        active  = [False]

        def norm(key):
            try:
                return kb.HotKey._normalize(key)
            except Exception:
                return key

        def on_press(key):
            pressed.add(norm(key))
            if not active[0] and combo.issubset(pressed):
                active[0] = True
                QTimer.singleShot(0, self._on_ptt_on)

        def on_release(key):
            k = norm(key)
            if active[0] and k in combo:
                active[0] = False
                QTimer.singleShot(0, self._on_ptt_off)
            pressed.discard(k)

        self._kb_listener = kb.Listener(on_press=on_press, on_release=on_release)
        self._kb_listener.start()

    # ---- 生命周期 ----------------------------------------------------------
    def start(self):
        mode      = config.get("mode")
        toggle_hk = config.get("toggle_hotkey") or ""
        ptt_hk    = config.get("ptt_hotkey")    or ""

        if mode == "toggle":
            if toggle_hk.startswith("<mouse:"):
                btn = toggle_hk.replace("<mouse:", "").rstrip(">")
                self._start_mouse(btn, is_ptt=False)
            elif toggle_hk:
                self._reg(HK_TOGGLE, toggle_hk)
        else:  # ptt
            if ptt_hk.startswith("<mouse:"):
                btn = ptt_hk.replace("<mouse:", "").rstrip(">")
                self._start_mouse(btn, is_ptt=True)
            elif ptt_hk:
                self._start_kb_ptt(ptt_hk)

    def stop(self):
        self._unreg_all()
        if self._mouse_stop is not None:
            self._mouse_stop.set()
            self._mouse_stop = None
        if self._kb_listener is not None:
            try:
                self._kb_listener.stop()
            except Exception:
                pass
        self._kb_listener = None

    def restart(self):
        self.stop()
        self.start()

# ---------------------------------------------------------------------------
# 矢量麦克风绘制
# ---------------------------------------------------------------------------
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
# 浮动指示器
# ---------------------------------------------------------------------------
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

        # 不使用 QGraphicsDropShadowEffect（与 TranslucentBackground 在部分 Windows 下冲突）
        self._drag_pos = None
        self._state    = "on"   # "on" | "mute" | "talking"
        self._level    = 0.0
        self._ptt      = False
        self._locked   = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(80)

    def _apply_size(self):
        self.setFixedSize(self.SIZE, self.SIZE)

    # 供外部直接调用
    def set_state(self, muted: bool, ptt: bool = False):
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
        try:
            hwnd = int(self.winId())
            ex = _user32.GetWindowLongPtrW(hwnd, -20)  # GWL_EXSTYLE
            if locked:
                _user32.SetWindowLongPtrW(hwnd, -20, ex | 0x00000020 | 0x00080000)  # WS_EX_TRANSPARENT | WS_EX_LAYERED
            else:
                _user32.SetWindowLongPtrW(hwnd, -20, ex & ~(0x00000020 | 0x00080000))
        except Exception:
            pass
        self.update()

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
        a_tog  = menu.addAction("取消静音" if mic.is_muted() else "静音麦克风")
        a_set  = menu.addAction("设置…")
        menu.addSeparator()
        a_lock = menu.addAction("锁定指示器")
        a_lock.triggered.connect(self.lockRequested.emit)
        menu.addSeparator()
        a_hide = menu.addAction("隐藏指示器")
        menu.addSeparator()
        a_quit = menu.addAction("退出")
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

        # 三角路径
        tri = QPainterPath()
        h = r * 0.85
        y0 = r - h * 0.55
        tri.moveTo(r, y0 - h)
        tri.lineTo(r - h * 0.9, y0 + h * 0.5)
        tri.lineTo(r + h * 0.9, y0 + h * 0.5)
        tri.closeSubpath()

        muted = self._state == "mute"
        locked = self._locked

        # 锁定时更透明
        bg_alpha = 120 if locked else 190
        if muted:
            bg = QColor(25, 20, 20, bg_alpha)
        else:
            bg = QColor(18, 18, 22, bg_alpha)

        # 软阴影 (锁定时无阴影)
        if not locked:
            for i in range(3, 0, -1):
                p.setBrush(QColor(0, 0, 0, 8 - i * 1))
                p.setPen(Qt.PenStyle.NoPen)
                p.translate(0, i * 1.5)
                p.drawPath(tri)
                p.translate(0, -i * 1.5)

        # 背景
        p.setBrush(bg); p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(tri)

        # 微高光 (锁定时不画)
        if not locked:
            hl = QPainterPath()
            hl.moveTo(r, y0 - h)
            hl.lineTo(r - h * 0.45, y0 - h * 0.35)
            hl.lineTo(r + h * 0.45, y0 - h * 0.35)
            hl.closeSubpath()
            p.setBrush(QColor(255, 255, 255, 30))
            p.drawPath(hl)

        # 音量环 (锁定时也保留)
        if not muted and self._level > 0.01:
            perim = 5.4 * h
            lvl = min(1.0, self._level * 4)
            dp = [perim * lvl, perim * (1 - lvl)]
            ring_pen = QPen(QColor(255, 255, 255, 190), 2.5,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            ring_pen.setDashPattern(dp)
            p.setPen(ring_pen); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(tri)

        # 锁定时: 只画小圆点, 不画文字/小三角
        if locked:
            dot_color = QColor(255, 170, 170, 140) if muted else QColor(255, 255, 255, 120)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(dot_color)
            p.drawEllipse(QPointF(r, r), s * 0.07, s * 0.07)
            p.end()
            return

        # 文字/图标颜色 (静音时极淡粉)
        accent = QColor(255, 160, 160) if muted else QColor(255, 255, 255)
        label  = "MUTE" if muted else ("TALK" if self._state == "talking" else "ON")

        # 描边 (静音时极淡)
        if muted:
            p.setPen(QPen(QColor(255, 160, 160, 60), 1.2))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 50), 0.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(tri)

        # 中间小三角
        tiny_r = s * 0.08
        tiny = QPainterPath()
        y1 = r - s * 0.02
        tiny.moveTo(r, y1 - tiny_r * 1.5)
        tiny.lineTo(r - tiny_r * 1.3, y1 + tiny_r * 0.6)
        tiny.lineTo(r + tiny_r * 1.3, y1 + tiny_r * 0.6)
        tiny.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawPath(tiny)

        # 状态文字
        font = QFont("Microsoft YaHei UI", max(6, int(s * 0.13)))
        font.setBold(True)
        p.setFont(font); p.setPen(QPen(accent))
        p.drawText(QRectF(0, r + s * 0.07, s, s * 0.25), Qt.AlignmentFlag.AlignCenter, label)
        p.end()

# ---------------------------------------------------------------------------
# 设置窗口
# ---------------------------------------------------------------------------
class SettingsWindow(QWidget):
    saved = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} 设置")
        self.setWindowIcon(make_tray_icon(False))
        self.resize(450, 520)
        self.setMinimumSize(430, 500)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 26, 30, 24)
        root.setSpacing(12)

        sub_style = ("color:rgba(0,0,0,.5);" if not isDarkTheme()
                     else "color:rgba(255,255,255,.5);")
        hint_style = ("color:rgba(0,0,0,.42);" if not isDarkTheme()
                      else "color:rgba(255,255,255,.42);")

        title = TitleLabel(f"{APP_NAME} 设置")
        sub   = CaptionLabel("快捷键 · 工作模式 · 外观")
        sub.setStyleSheet(sub_style)
        root.addWidget(title); root.addWidget(sub); root.addSpacing(10)

        # 模式
        root.addWidget(StrongBodyLabel("工作模式"))
        self._mg = QButtonGroup(self)
        self._rb_tog = RadioButton("切换静音   按一下切换开/关")
        self._rb_ptt = RadioButton("按住说话   按住时临时取消静音")
        self._mg.addButton(self._rb_tog, 0)
        self._mg.addButton(self._rb_ptt, 1)
        (self._rb_ptt if config.get("mode") == "ptt" else self._rb_tog).setChecked(True)
        mb = QVBoxLayout(); mb.setSpacing(8)
        mb.addWidget(self._rb_tog); mb.addWidget(self._rb_ptt)
        root.addLayout(mb); root.addSpacing(4)

        # 快捷键
        root.addWidget(StrongBodyLabel("切换快捷键"))
        self._ed_tog = QLineEdit(config.get("toggle_hotkey") or "")
        self._ed_tog.setPlaceholderText("例如: ctrl+shift+m")
        self._ed_tog.setFixedHeight(38)
        root.addWidget(self._ed_tog)

        root.addWidget(StrongBodyLabel("按住说话键"))
        self._ed_ptt = QLineEdit(config.get("ptt_hotkey") or "")
        self._ed_ptt.setPlaceholderText("例如: ctrl+alt+space  或  <mouse:x2>")
        self._ed_ptt.setFixedHeight(38)
        root.addWidget(self._ed_ptt)

        hint = CaptionLabel("格式: ctrl+shift+m  /  alt+f4  /  <mouse:x1>  等")
        hint.setStyleSheet(hint_style)
        root.addWidget(hint); root.addSpacing(8)

        # 外观
        root.addWidget(StrongBodyLabel("外观"))
        self._cb_show = CheckBox("显示浮动指示器")
        self._cb_show.setChecked(bool(config.get("show_indicator")))
        root.addWidget(self._cb_show)

        sz_row = QHBoxLayout(); sz_row.setSpacing(8)
        sz_row.addWidget(BodyLabel("指示器大小"))
        self._sg = QButtonGroup(self)
        cur_sz = config.get("indicator_size", 48)
        for lbl, val in [("小", 48), ("中", 64), ("大", 80)]:
            rb = RadioButton(lbl)
            rb.setProperty("v", val)
            if val == cur_sz:
                rb.setChecked(True)
            self._sg.addButton(rb)
            sz_row.addWidget(rb)
        sz_row.addStretch(1)
        root.addLayout(sz_row)

        sz_hint = CaptionLabel("浮动指示器可拖动，位置会自动记忆")
        sz_hint.setStyleSheet(hint_style)
        root.addWidget(sz_hint)

        # 开机启动
        self._cb_autostart = CheckBox("开机自动启动")
        self._cb_autostart.setChecked(get_auto_start())
        root.addWidget(self._cb_autostart)

        self._cb_admin = CheckBox("下次以管理员身份启动（修复部分系统热键不生效）")
        self._cb_admin.setChecked(bool(config.get("run_as_admin")))
        root.addWidget(self._cb_admin)
        root.addStretch(1)

        # 按钮
        br = QHBoxLayout(); br.setSpacing(12)
        btn_cancel = PrimaryPushButton("关闭")
        btn_cancel.setFixedHeight(40); btn_cancel.clicked.connect(self.close)
        btn_save   = PrimaryPushButton("保存并应用")
        btn_save.setFixedHeight(40); btn_save.clicked.connect(self._save)
        br.addStretch(1); br.addWidget(btn_cancel); br.addWidget(btn_save)
        root.addLayout(br)

    def _record(self, which: str):
        if self._recording[which]:
            return
        self._recording[which] = True
        btn = self._btn_tog if which == "toggle" else self._btn_ptt
        btn.setText("⏺ 等待按键…"); btn.setEnabled(False)

        def on_done(spec):
            def apply():
                if spec:
                    config.set("toggle_hotkey" if which == "toggle" else "ptt_hotkey", spec)
                self._btn_tog.setText(config.get("toggle_hotkey") or "未设置")
                self._btn_ptt.setText(config.get("ptt_hotkey") or "未设置")
                btn.setEnabled(True)
                self._recording[which] = False
            QTimer.singleShot(0, apply)

        record_hotkey(on_done)

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
# 主应用
# ---------------------------------------------------------------------------
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

        # 指示器
        self.ind = FloatIndicator()
        self.ind.toggled.connect(self._do_toggle)
        self.ind.settingsRequested.connect(self.open_settings)
        self.ind.hideRequested.connect(self._hide_ind)
        self.ind.lockRequested.connect(self._toggle_lock)
        self.ind.quitRequested.connect(self.shutdown)

        # 热键 (必须在 QApplication 存在后创建)
        self.hk = HotkeyManager(
            on_toggle  = self._do_toggle,
            on_ptt_on  = self._ptt_on,
            on_ptt_off = self._ptt_off,
        )

        # PTT 模式启动时默认静音
        if config.get("mode") == "ptt":
            mic.mute()

        # 托盘
        self.tray = QSystemTrayIcon(make_tray_icon(mic.is_muted()))
        self.tray.setToolTip(APP_NAME)
        self._build_tray()
        self.tray.activated.connect(self._tray_click)
        self.tray.show()

        # 启动
        self.hk.start()
        self._apply_vis()
        self._place_ind()

    # ---- 核心操作 ----------------------------------------------------------
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
        self.tray.setToolTip(f"{APP_NAME} — {'已静音' if muted else '已开启'}")
        if hasattr(self, "act_state"):
            self.act_state.setText("麦克风：已静音" if muted else "麦克风：已开启")
        self.ind.set_state(muted, self._ptt)
        if sound:
            _beep(muted)

    # ---- 指示器 ------------------------------------------------------------
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

    def _show_ind(self):
        config.set("show_indicator", True)
        config.save()
        self.ind.show()

    # ---- 托盘 --------------------------------------------------------------
    def _build_tray(self):
        m = QMenu()
        muted = mic.is_muted()
        self.act_state = QAction("麦克风：已静音" if muted else "麦克风：已开启", m)
        self.act_state.triggered.connect(self._do_toggle)
        m.addAction(self.act_state)
        m.addSeparator()
        # 切换模式
        mode = config.get("mode")
        act_mode = QAction("切换到按键开麦模式" if mode == "toggle" else "切换到切换模式", m)
        act_mode.triggered.connect(self._toggle_mode)
        m.addAction(act_mode)
        m.addSeparator()
        a = QAction("设置…", m); a.triggered.connect(self.open_settings); m.addAction(a)
        show = config.get("show_indicator")
        a2 = QAction("隐藏浮动指示器" if show else "显示浮动指示器", m)
        a2.triggered.connect(self._hide_ind if show else self._show_ind)
        m.addAction(a2)
        self.act_lock = QAction("锁定指示器" if not self.ind._locked else "解锁指示器", m)
        self.act_lock.triggered.connect(self._toggle_lock)
        m.addAction(self.act_lock)
        m.addSeparator()
        a3 = QAction("退出", m); a3.triggered.connect(self.shutdown); m.addAction(a3)
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
        self._build_tray()

    def _tray_click(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._do_toggle()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_settings()

    # ---- 设置窗口 ----------------------------------------------------------
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

    # ---- 生命周期 ----------------------------------------------------------
    def shutdown(self):
        self.hk.stop()
        # 退出时无条件强制恢复所有麦克风，不依赖内部状态
        try:
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
