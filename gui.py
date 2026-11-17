"""Launch the local Yolbulan desktop UI in Microsoft Edge WebView2."""
import ctypes
import sys
import webview
from webview.guilib import initialize

# Keep the source launcher imports used by PotPlayer's subtitle helper.
from yolbulan_api import BASE, DEFAULTS, SETTINGS, YolbulanApi, configure_cuda


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
            window = webview.create_window('Yolbulan', str(index), js_api=api, width=1460, height=900,
                                           min_size=(790, 540), background_color='#f8f5f1', text_select=True)
            api.bind_window(window)
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
