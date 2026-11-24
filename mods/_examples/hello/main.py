"""最小可用示例模组。

规则就三条：
1. on_load(host) 里只做注册，把 host 存下来给后面用
2. 真业务放 on_enable
3. on_disable 要把自己起的东西停干净
"""

_HOST = None


def on_load(host):
    global _HOST
    _HOST = host
    host.log.info(f"hello 加载完成，宿主版本 {host.app_version}")
    host.events.on("game.started", _on_game_started)


def on_enable():
    _HOST.log.info("hello 已启用")
    _HOST.notify("示例模组", "启用成功了，这条通知就是通过 host.notify 发的")


def on_disable():
    _HOST.log.info("hello 已停用")


def on_unload():
    _HOST.log.info("hello 已卸载")


def _on_game_started(**kw):
    _HOST.log.info(f"检测到游戏启动：{kw.get('process')}")
