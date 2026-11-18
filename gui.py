"""Launch the local Yolbulan desktop UI in Microsoft Edge WebView2."""
import ctypes
import sys
from ctypes import wintypes
import webview
from webview.guilib import initialize

# Keep the source launcher imports used by PotPlayer's subtitle helper.
from yolbulan_api import BASE, DEFAULTS, SETTINGS, YolbulanApi, configure_cuda


class WindowPosition(ctypes.Structure):
    _fields_ = [('hwnd', wintypes.HWND), ('after', wintypes.HWND),
                ('x', ctypes.c_int), ('y', ctypes.c_int),
                ('width', ctypes.c_int), ('height', ctypes.c_int), ('flags', wintypes.UINT)]


def window_background(theme):
    if theme == 'system':
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                theme = 'light' if winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] else 'dark'
        except OSError:
            theme = 'light'
    return '#202321' if theme == 'dark' else '#f7f7f4'


def install_window_frame(window):
    """Make room for the web title bar while retaining the Windows resize frame."""
    from System import InvalidOperationException
    from System.Windows.Forms import Cursor, FormStartPosition, Screen

    native = window.native
    work_area = Screen.FromPoint(Cursor.Position).WorkingArea
    width, height = min(native.Width, work_area.Width), min(native.Height, work_area.Height)
    native.StartPosition = FormStartPosition.Manual
    native.SetBounds(work_area.X + (work_area.Width - width) // 2,
                     work_area.Y + (work_area.Height - height) // 2, width, height)

    user32 = ctypes.windll.user32
    comctl32 = ctypes.windll.comctl32
    wm_ncdestroy, wm_nccalcsize = 0x0082, 0x0083
    wm_windowposchanging, wm_windowposchanged = 0x0046, 0x0047
    swp_nosize, swp_nomove = 0x0001, 0x0002
    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        ctypes.c_size_t, ctypes.c_size_t,
    )
    default = comctl32.DefSubclassProc
    default.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    default.restype = ctypes.c_ssize_t
    add = comctl32.SetWindowSubclass
    add.argtypes = (wintypes.HWND, callback_type, ctypes.c_size_t, ctypes.c_size_t)
    add.restype = wintypes.BOOL
    remove = comctl32.RemoveWindowSubclass
    remove.argtypes = (wintypes.HWND, callback_type, ctypes.c_size_t)
    remove.restype = wintypes.BOOL
    set_position = user32.SetWindowPos
    set_position.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, wintypes.UINT)
    set_position.restype = wintypes.BOOL
    is_zoomed, is_iconic = user32.IsZoomed, user32.IsIconic
    for query in (is_zoomed, is_iconic):
        query.argtypes = (wintypes.HWND,)
        query.restype = wintypes.BOOL
    was_normal = True
    restoring = False

    @callback_type
    def frame_proc(hwnd, message, wparam, lparam, subclass_id, _data):
        nonlocal was_normal, restoring
        if message == wm_nccalcsize:
            rect = wintypes.RECT.from_address(lparam)
            top, left = rect.top, rect.left
            default(hwnd, message, wparam, lparam)
            rect.top = top + (rect.left - left)
            return 0
        if message == wm_windowposchanging and restoring:
            # Windows has already restored the outer bounds. WinForms otherwise
            # applies the old native title bar height to the restored client size.
            WindowPosition.from_address(lparam).flags |= swp_nosize | swp_nomove
        if message == wm_windowposchanged and not restoring:
            normal = not (is_zoomed(hwnd) or is_iconic(hwnd))
            restoring = normal and not was_normal
            was_normal = normal
            try:
                return default(hwnd, message, wparam, lparam)
            finally:
                restoring = False
        if message == wm_ncdestroy:
            remove(hwnd, frame_proc, subclass_id)
        return default(hwnd, message, wparam, lparam)

    def enable_drag(sender, args):
        if args.IsSuccess:
            enable_non_client_regions(sender)

    def enable_non_client_regions(browser):
        try:
            browser.CoreWebView2.Settings.IsNonClientRegionSupportEnabled = True
        except (AttributeError, InvalidOperationException):
            return
        hwnd = native.Handle.ToInt64()
        if add(hwnd, frame_proc, 1, 0):
            window._frame_proc = frame_proc
            # SWP_FRAMECHANGED | SWP_NOACTIVATE | SWP_NOZORDER | SWP_NOMOVE | SWP_NOSIZE
            set_position(hwnd, None, 0, 0, 0, 0, 0x0037)

    browser = native.webview
    if browser.CoreWebView2 is None:
        browser.CoreWebView2InitializationCompleted += enable_drag
    else:
        enable_non_client_regions(browser)


def main():
    if sys.platform != 'win32':
        raise RuntimeError('Yolbulan Windows üzerinde çalışır.')
    try:
        if initialize('edgechromium').renderer != 'edgechromium':
            raise RuntimeError('Yolbulan için Microsoft Edge WebView2 Runtime kurulmalıdır.')
        index = BASE / 'frontend' / 'index.html'
        if not index.is_file():
            raise RuntimeError('Yolbulan arayüz dosyaları bulunamadı.')
        api = YolbulanApi()
        try:
            background = window_background(api.get_state()['settings']['theme'])
            window = webview.create_window('Yolbulan', str(index), js_api=api, width=1460, height=900,
                                           min_size=(790, 540), background_color=background, text_select=True)
            api.bind_window(window)
            window.events.before_show += install_window_frame
            window.events.closing += api.on_closing
            webview.start(gui='edgechromium', icon=str(BASE / 'Yolbulan.ico'))
        finally:
            api.close()
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(None, str(exc), 'Yolbulan başlatılamadı', 0x10)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
