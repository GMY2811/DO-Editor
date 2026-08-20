"""自动更新检查：后台线程查 GitHub Releases API，对比版本号，结果通过信号回主线程。"""
import json
import urllib.request

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

import app_config as cfg
import i18n

GITHUB_API = "https://api.github.com/repos/GMY2811/DO-Editor/releases/latest"
GITHUB_RELEASE_URL = "https://github.com/GMY2811/DO-Editor/releases/latest"
_TIMEOUT = 8


def _to_tuple(v):
    out = []
    for p in (v or "").split("."):
        if p.isdigit():
            out.append(int(p))
    return tuple(out)


class UpdateCheckWorker(QThread):
    result = Signal(dict)

    def run(self):
        try:
            req = urllib.request.Request(GITHUB_API, headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "DOEditor",
            })
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
            remote = (data.get("tag_name") or "").lstrip("v")
            local = cfg.APP_VERSION
            url = data.get("html_url") or GITHUB_RELEASE_URL
            rt, lt = _to_tuple(remote), _to_tuple(local)
            available = bool(rt) and bool(lt) and rt > lt
            self.result.emit({
                "available": available,
                "remote_ver": remote,
                "local_ver": local,
                "url": url,
                "name": data.get("name") or remote,
                "prerelease": bool(data.get("prerelease", False)),
                "error": None,
            })
        except Exception as e:
            self.result.emit({
                "available": False,
                "error": str(e),
                "local_ver": cfg.APP_VERSION,
                "url": GITHUB_RELEASE_URL,
            })


def check_update_async(parent, manual=False):
    """异步检查更新；manual=True 表示来自「检查更新」菜单，失败/无更新都要反馈。"""
    worker = UpdateCheckWorker(parent)

    def _on_result(d):
        try:
            err = d.get("error")
            if err:
                if manual:
                    QMessageBox.warning(
                        parent, i18n.tr("update_dialog_title"),
                        i18n.tr("update_failed").format(err=err))
                return
            if d.get("available"):
                box = QMessageBox(parent)
                box.setIcon(QMessageBox.Icon.Information)
                box.setWindowTitle(i18n.tr("update_dialog_title"))
                box.setText(i18n.tr("update_available").format(
                    ver=d["remote_ver"]))
                open_btn = box.addButton(
                    i18n.tr("update_open_release"),
                    QMessageBox.ButtonRole.AcceptRole)
                box.addButton(i18n.tr("update_later"),
                              QMessageBox.ButtonRole.RejectRole)
                box.exec()
                if box.clickedButton() is open_btn:
                    QDesktopServices.openUrl(QUrl(d["url"]))
            elif manual:
                QMessageBox.information(
                    parent, i18n.tr("update_dialog_title"),
                    i18n.tr("update_none"))
        finally:
            worker.deleteLater()

    worker.result.connect(_on_result)
    worker.start()