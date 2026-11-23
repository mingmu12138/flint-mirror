# -*- coding: utf-8 -*-
"""局域网小服务：手机扫码打开一个网页，四页——电脑状态 / 三角洲情报 / 文件互传 / 剪贴板。

为什么不做图片剪贴板：手机浏览器打开的是 http://192.168.x.x，不是 HTTPS。
Chrome 只在这类"安全上下文"里放开 navigator.clipboard，
所以纯局域网 http 页面里"一键把图写进手机剪贴板"根本做不到。

文件怎么走：
  电脑 → 手机   把文件丢进程序目录下的「分享」文件夹，手机上点一下就下载。
  手机 → 电脑   手机选文件直接传，边收边写盘，不读进内存，几个 G 的视频也能收。
"""
from __future__ import annotations

import io
import json
import ctypes
import mimetypes
import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from PySide6 import QtCore

HIST_MAX = 10
MAX_TEXT = 400_000          # 一段文字不该超过这个体积
CHUNK = 1 << 20             # 上传时每次 1MB，边收边写
MIN_FREE = 200 << 20        # 收到只剩 200MB 就别再往里写了
SHARE_NAME = "分享"
RECV_NAME = "收到"
FILE_LIST_MAX = 300


PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0d1117">
<title>燧镜</title>
<style>
:root{
  --bg-grad: radial-gradient(120% 78% at 50% -8%, #1b2330 0%, #0d1117 58%, #080a0f 100%);
  --fg:#e6ebf2; --fg2:#9aa3b2; --fg3:#6d7787;
  --card:rgba(255,255,255,.05); --card-bd:rgba(255,255,255,.10);
  --card-solid:#121821; --card-bd-solid:rgba(255,255,255,.07);
  --tile:rgba(0,0,0,.26); --tile-bd:rgba(255,255,255,.07);
  --line:rgba(0,0,0,.24); --line-bd:rgba(255,255,255,.06);
  --pre:rgba(0,0,0,.28);
  --nav:rgba(10,14,19,.90); --nav-bd:rgba(255,255,255,.08); --nav-ic:#7d8695;
  --accent:#20ffe0; --accent2:#17c8a8;
  --accent-bd:rgba(32,255,224,.55); --accent-bg:rgba(32,255,224,.12);
  --warn:#ff9f43; --bad:#ff8a8a;
  --wall:none;
  --wall-mask:linear-gradient(rgba(8,10,15,.58),rgba(8,10,15,.80));
}
body.light{
  --bg-grad: radial-gradient(112% 62% at 6% -10%,#cdeef2 0%,rgba(205,238,242,0) 66%),
    radial-gradient(100% 56% at 100% 4%,#e0d6fb 0%,rgba(224,214,251,0) 68%),
    linear-gradient(180deg,#fbfcfe 0%,#eef1f7 46%,#e4e8f1 100%);
  --fg:#1a1f28; --fg2:#5d6675; --fg3:#8a94a3;
  --card:rgba(255,255,255,.54); --card-bd:rgba(0,0,0,.07);
  --card-solid:#ffffff; --card-bd-solid:rgba(0,0,0,.07);
  --tile:#f2f5fa; --tile-bd:rgba(0,0,0,.06);
  --line:#f2f5fa; --line-bd:rgba(0,0,0,.05);
  --pre:#f6f8fb;
  --nav:rgba(255,255,255,.95); --nav-bd:rgba(0,0,0,.07); --nav-ic:#7b8494;
  --accent:#0f9d8f; --accent2:#0b8a7d;
  --accent-bd:rgba(15,157,143,.45); --accent-bg:rgba(15,157,143,.09);
  --warn:#b8720a; --bad:#d64545;
  --wall-mask:linear-gradient(rgba(252,253,255,.44),rgba(244,248,252,.62));
}
body:not(.glass){
  --card: var(--card-solid);
  --card-bd: var(--card-bd-solid);
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;height:100%}
body{color:var(--fg);background:var(--bg-grad);background-attachment:fixed;
font:15px/1.5 -apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif;
display:flex;flex-direction:column;transition:background .25s ease,color .25s ease}
.head{padding:16px 16px 8px;flex:none}
.head h1{margin:0;font-size:17px;letter-spacing:.4px}
.head .sub{margin-top:3px;font-size:11.5px;color:var(--fg3)}
.dot{display:inline-block;width:7px;height:7px;margin-left:7px;border-radius:50%;
background:rgba(128,128,128,.55);vertical-align:2px}
.dot.on{background:var(--accent);box-shadow:0 0 8px var(--accent)}
#wrap{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:0 16px 104px}
.page{display:none}
.page.on{display:block}
.card{margin-bottom:12px;padding:14px;border:1px solid var(--card-bd);border-radius:16px;
background:var(--card);transition:background .25s ease,border-color .25s ease}
body.glass .card{-webkit-backdrop-filter:blur(15px) saturate(135%);backdrop-filter:blur(15px) saturate(135%)}
.labw{display:flex;align-items:center;gap:6px}
.dtmark{width:16px;height:16px;stroke:#3be07e;flex:none}
.lab{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;
font-size:12.5px;color:var(--fg2)}
.hint{color:var(--fg3);font-size:11.5px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.tile{padding:12px;border-radius:13px;background:var(--tile);border:1px solid var(--tile-bd)}
.tk{font-size:11.5px;color:var(--fg2);margin-bottom:6px}
.tv{font:20px/1.1 ui-monospace,Consolas,monospace;font-weight:600;
font-variant-numeric:tabular-nums;color:var(--fg)}
.tu{font-size:11px;color:var(--fg3);margin-top:4px}
.bar{margin-top:9px;height:5px;border-radius:3px;background:var(--line);overflow:hidden}
.bar i{display:block;height:100%;width:0;border-radius:3px;
background:linear-gradient(90deg,var(--accent2),var(--accent));transition:width .35s ease}
.foot{margin-top:10px;font-size:11.5px;color:var(--fg2);line-height:1.6}
.mnow{display:flex;align-items:center;gap:11px}
.mcov{width:48px;height:48px;border-radius:12px;flex:none;background:var(--tile);
border:1px solid var(--tile-bd);background-size:cover;background-position:center;
display:flex;align-items:center;justify-content:center;color:var(--fg3)}
.mcov svg{width:17px;height:17px;opacity:.7}
.mtxt{min-width:0;flex:1}
.mt1{font-size:14.5px;font-weight:600;color:var(--fg);white-space:nowrap;
overflow:hidden;text-overflow:ellipsis}
.mt2{font-size:11.5px;color:var(--fg3);margin-top:2px;white-space:nowrap;
overflow:hidden;text-overflow:ellipsis}
.mbar{margin-top:12px;height:5px;border-radius:3px;background:var(--line);overflow:hidden}
.mbar i{display:block;height:100%;width:0;border-radius:3px;
background:linear-gradient(90deg,var(--accent2),var(--accent));transition:width .3s linear}
.mtime{display:flex;justify-content:space-between;margin-top:5px;
font:11px/1 ui-monospace,Consolas,monospace;color:var(--fg3)}
.mctl{display:flex;align-items:center;justify-content:center;gap:16px;margin-top:13px}
.mctl .mbtn{width:46px;height:46px;margin:0;padding:0;border-radius:50%;
border:1px solid var(--card-bd);background:var(--tile);color:var(--fg2);
display:flex;align-items:center;justify-content:center}
.mctl .mbtn.big{width:58px;height:58px;border-color:var(--accent-bd);
background:var(--accent-bg);color:var(--accent)}
.mctl .mbtn svg{width:19px;height:19px;fill:currentColor;stroke:none}
.mctl .mbtn.big svg{width:23px;height:23px}
.mctl .mbtn:disabled{opacity:.42}
pre{margin:0;padding:10px;max-height:34vh;overflow:auto;white-space:pre-wrap;word-break:break-all;
-webkit-user-select:text;user-select:text;
border:1px solid var(--line-bd);border-radius:11px;background:var(--pre);
font:13px/1.55 ui-monospace,Consolas,monospace;color:var(--fg)}
textarea{width:100%;min-height:84px;padding:10px;resize:vertical;outline:none;
border:1px solid var(--line-bd);border-radius:11px;background:var(--pre);
color:var(--fg);font:13px/1.55 ui-monospace,Consolas,monospace}
textarea::placeholder{color:var(--fg3)}
textarea:focus{border-color:var(--accent)}
button{width:100%;margin-top:10px;padding:11px;border-radius:11px;font-size:14px;font-weight:600;
border:1px solid var(--accent-bd);background:var(--accent-bg);color:var(--accent);
font-family:inherit}
button:active{filter:brightness(1.25)}
button.ghost{border-color:var(--card-bd);background:var(--tile);color:var(--fg2);font-weight:500}
button.mini{width:auto;margin:0;padding:5px 12px;font-size:12px;font-weight:500;
border-radius:8px;background:var(--accent-bg);border-color:var(--accent-bd)}
button.mini[disabled]{opacity:.45}
.seg{display:flex;gap:8px}
.seg button{flex:1;margin:0;padding:10px;border-radius:10px;font-size:13px;font-weight:500;
border:1px solid var(--card-bd);background:var(--tile);color:var(--fg2)}
.seg button.on{border-color:var(--accent-bd);background:var(--accent-bg);color:var(--accent);font-weight:600}
body.glass .card.shortcut{-webkit-backdrop-filter:blur(15px) saturate(135%);backdrop-filter:blur(15px) saturate(135%)}
/* 浅色玻璃：纯白叠加只会糊成一片，靠上下厚薄 + 内高光 + 冷调阴影出质感 */
body.light.glass .card{background:linear-gradient(166deg,rgba(255,255,255,.78) 0%,rgba(255,255,255,.42) 38%,rgba(255,255,255,.27) 100%);
border-color:rgba(255,255,255,.78);
box-shadow:0 6px 18px rgba(24,56,78,.09),inset 0 1px 0 rgba(255,255,255,.96),
inset 0 -16px 24px -20px rgba(24,56,78,.30);
-webkit-backdrop-filter:blur(14px) saturate(200%);backdrop-filter:blur(14px) saturate(200%)}
body.light.glass .tile{background:rgba(255,255,255,.44);border-color:rgba(255,255,255,.62)}
body.light.glass .line{background:rgba(255,255,255,.40);border-color:rgba(255,255,255,.55)}
body.light.glass pre,body.light.glass textarea{background:rgba(255,255,255,.55)}
body.light.glass .nav{background:linear-gradient(180deg,rgba(255,255,255,.86),rgba(255,255,255,.62));
border-top-color:rgba(255,255,255,.90);
box-shadow:0 -8px 26px rgba(24,56,78,.10),inset 0 1px 0 rgba(255,255,255,.96);
-webkit-backdrop-filter:blur(16px) saturate(190%);backdrop-filter:blur(16px) saturate(190%)}
/* 深色顺手加一道顶边高光，别改动太大 */
body:not(.light).glass .card{box-shadow:0 8px 26px rgba(0,0,0,.22),inset 0 1px 0 rgba(255,255,255,.07)}
.shortcut{cursor:pointer}
.shortcut:active{filter:brightness(1.05)}
.srow{display:flex;align-items:center;gap:12px}
.sico{flex:none;width:40px;height:40px;border-radius:12px;display:flex;
align-items:center;justify-content:center;background:var(--accent-bg)}
.sico svg{width:21px;height:21px;stroke:var(--accent)}
.stxt{flex:1;min-width:0}
.st1{font-size:13.5px;font-weight:600;color:var(--fg)}
.st2{font-size:11.5px;color:var(--fg3);margin-top:3px;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.sarw{flex:none;color:var(--fg3);font-size:18px;line-height:1}
body.haswall{background-image:var(--wall-mask),var(--wall);
background-size:cover,cover;background-position:center,center;
background-repeat:no-repeat,no-repeat;background-attachment:fixed,fixed}
.wprev{height:104px;margin-bottom:10px;border:1px dashed var(--card-bd);border-radius:12px;
background:var(--line) center/cover no-repeat;display:flex;align-items:center;
justify-content:center;font-size:12px;color:var(--fg3);overflow:hidden}
.wprev:not(.empty){border-style:solid}
#msg{position:fixed;left:0;right:0;bottom:78px;padding:0 16px;min-height:20px;
font-size:12.5px;color:var(--fg3);pointer-events:none;text-align:center}
.blk{padding-top:11px;margin-top:11px;border-top:1px solid var(--line-bd)}
.blk:first-child{padding-top:0;margin-top:0;border-top:none}
.blkhead{display:flex;align-items:center;gap:8px;margin-bottom:7px}
.blkhead span{font-size:12.5px;color:var(--fg);font-weight:600;flex:1;min-width:0}
.blkhead em{font-style:normal;font-size:11px;color:var(--fg3);margin-right:2px}
.line{display:flex;align-items:center;justify-content:space-between;gap:10px;
padding:6px 9px;margin-bottom:5px;border-radius:9px;background:var(--line);
border:1px solid var(--line-bd);font-size:12.5px}
.line .n{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--fg)}
.line .v{flex:none;font:12.5px/1 ui-monospace,Consolas,monospace;color:var(--fg);font-variant-numeric:tabular-nums}
.line .v.g{color:var(--accent)}
.line .v.o{color:var(--warn)}
.line.pwd{cursor:pointer}
.line.pwd .v{color:var(--accent);letter-spacing:1px;font-weight:700}
.empty{font-size:12.5px;color:var(--fg3)}
.row{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.row:last-child{margin-bottom:0}
.txt{flex:1;min-width:0;padding:8px 10px;border-radius:10px;background:var(--line);
border:1px solid var(--line-bd);font:12.5px/1.45 ui-monospace,Consolas,monospace;
color:var(--fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .mini2{flex:none;width:auto;margin:0;padding:7px 13px;font-size:12.5px;font-weight:500;
border-radius:9px;border:1px solid var(--accent-bd);background:var(--accent-bg);color:var(--accent)}
.row .mini2.x{width:36px;padding:7px 0;border-color:var(--card-bd);
background:var(--tile);color:var(--fg3);font-weight:400;font-size:15px}
.fitem{display:flex;align-items:center;gap:10px;padding:9px 10px;margin-bottom:6px;
border-radius:11px;background:var(--line);border:1px solid var(--line-bd)}
.fitem .fico{flex:none;width:32px;height:32px;border-radius:9px;display:flex;
align-items:center;justify-content:center;font-size:11px;font-weight:700;
background:var(--accent-bg);color:var(--accent)}
.fitem .fname{flex:1;min-width:0}
.fitem .fn{font-size:12.5px;color:var(--fg);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fitem .fm{font-size:10.5px;color:var(--fg3);margin-top:2px}
.fitem a{flex:none;padding:6px 12px;border-radius:8px;font-size:12px;font-weight:600;
text-decoration:none;border:1px solid var(--accent-bd);background:var(--accent-bg);color:var(--accent)}
.prog{height:7px;border-radius:4px;background:var(--line);overflow:hidden;margin-top:9px}
.prog i{display:block;height:100%;width:0;border-radius:4px;
background:linear-gradient(90deg,var(--accent2),var(--accent));transition:width .2s linear}
.nav{position:fixed;left:0;right:0;bottom:0;display:flex;
padding:7px 4px calc(7px + env(safe-area-inset-bottom));
background:var(--nav);border-top:1px solid var(--nav-bd);
transition:background .25s ease}
body.glass .nav{-webkit-backdrop-filter:blur(18px) saturate(140%);backdrop-filter:blur(18px) saturate(140%)}
.nav button{flex:1;margin:0;padding:5px 0;background:none;border:none;border-radius:10px;
color:var(--nav-ic);font-size:10.5px;font-weight:500;display:flex;flex-direction:column;
align-items:center;gap:3px;white-space:nowrap}
.nav button.on{color:var(--accent)}
.nav svg{width:21px;height:21px;display:block}
.nav svg path,.nav svg rect,.nav svg circle,.nav svg line{stroke:var(--nav-ic)}
.nav button.on svg path,.nav button.on svg rect,.nav button.on svg circle,.nav button.on svg line{stroke:var(--accent)}

/* 断线遮罩：电脑那头没响应时盖住整页，别让它黑着 */
#clinlost{position:fixed;left:0;right:0;top:0;bottom:0;z-index:9999;display:none;
 align-items:center;justify-content:center;padding:22px;
 background:rgba(6,18,22,.86);
 -webkit-backdrop-filter:blur(16px);backdrop-filter:blur(16px)}
#clinlost.on{display:flex}
#clinlost .lcard{width:100%;max-width:420px;border-radius:20px;padding:22px 20px 18px;
 background:var(--card,#f7fbfc);border:1px solid var(--card-bd,rgba(0,0,0,.08));
 box-shadow:0 20px 54px rgba(0,0,0,.34)}
#clinlost .lt1{font-size:17px;font-weight:700;color:var(--fg,#123039);letter-spacing:.4px}
#clinlost .lt2{font-size:12.5px;line-height:1.75;color:var(--fg2,#42565f);margin-top:8px}
#clinlost .lt3{font-size:11.5px;color:var(--fg3,#8a9aa2);margin-top:10px}
#clinlost .lbtns{display:flex;gap:10px;margin-top:18px}
#clinlost button{margin:0;flex:1;padding:12px;border-radius:12px;font-size:13.5px}
#clinlost #lostother{border-color:var(--card-bd);background:var(--tile);color:var(--fg2);font-weight:500}
</style>
</head>
<body class="glass">

<div id="clinlost">
  <div class="lcard">
    <div class="lt1">和电脑断了连接</div>
    <div class="lt2">手机还开着这页，但电脑那头没回应了。<br>
      常见原因：电脑休眠 / 睡眠了、燧镜退出了、笔记本换了 WiFi 或者 IP 变了。</div>
    <div class="lt3" id="losthint">正在自动重试…</div>
    <div class="lbtns">
      <button id="lostretry">马上重连</button>
      <button id="lostother">换一台电脑</button>
    </div>
  </div>
</div>

<div class="head">
  <h1>燧镜<span id="dot" class="dot"></span></h1>
  <div class="sub">同一个 WiFi 内直连，不走公网，不经过任何服务器</div>
</div>

<div id="wrap">
  <!-- ============ 0 状态 ============ -->
  <div class="page on" id="pg0">
    <div class="card">
      <div class="lab"><span>电脑状态</span><span class="hint" id="sysat"></span></div>
      <div class="grid">
        <div class="tile"><div class="tk">CPU 占用</div><div class="tv" id="t1">–</div>
          <div class="bar"><i id="b1"></i></div></div>
        <div class="tile"><div class="tk">内存</div><div class="tv" id="t2">–</div>
          <div class="tu" id="u2"></div><div class="bar"><i id="b2"></i></div></div>
        <div class="tile"><div class="tk">显卡占用</div><div class="tv" id="t3">–</div>
          <div class="tu" id="u3"></div><div class="bar"><i id="b3"></i></div></div>
        <div class="tile"><div class="tk">显卡温度</div><div class="tv" id="t4">–</div>
          <div class="tu" id="u4"></div></div>
      </div>
      <div class="foot" id="f1"></div>
    </div>
    <div class="card shortcut" onclick="gotoPage(2)">
      <div class="srow">
        <div class="sico"><svg viewBox="0 0 24 24" fill="none" stroke-width="1.9" stroke-linecap="round">
          <line x1="8" y1="4" x2="8" y2="16"/><line x1="8" y1="16" x2="4.6" y2="12"/>
          <line x1="8" y1="16" x2="11.4" y2="12"/>
          <line x1="17" y1="20" x2="17" y2="8"/><line x1="17" y1="8" x2="20.4" y2="12"/>
          <line x1="17" y1="8" x2="13.6" y2="12"/>
        </svg></div>
        <div class="stxt"><div class="st1">文件互传</div>
          <div class="st2" id="sf1">电脑上的文件、手机传上去的东西</div></div>
        <div class="sarw">›</div>
      </div>
    </div>
    <div class="card shortcut" onclick="gotoPage(3)">
      <div class="srow">
        <div class="sico"><svg viewBox="0 0 24 24" fill="none" stroke-width="1.9" stroke-linecap="round">
          <rect x="5" y="4" width="14" height="16" rx="3"/>
          <line x1="9" y1="9" x2="15" y2="9"/><line x1="9" y1="13" x2="15" y2="13"/>
          <line x1="9" y1="17" x2="13" y2="17"/>
        </svg></div>
        <div class="stxt"><div class="st1">剪贴板</div>
          <div class="st2" id="sf2">电脑上复制的东西，手机上能拿</div></div>
        <div class="sarw">›</div>
      </div>
    </div>
    <div class="card">
      <div class="lab"><span>电脑音乐</span><span class="hint" id="mhint">空闲</span></div>
      <div class="mnow">
        <div class="mcov" id="mcov"><svg viewBox="0 0 24 24"><path d="M9 18.2a3 3 0 1 0 2-2.8V7.4l7-1.6v7.2a3 3 0 1 0 2-2.8"/></svg></div>
        <div class="mtxt">
          <div class="mt1" id="mt">没在放歌</div>
          <div class="mt2" id="ma">先在电脑的音乐页里点一首</div>
        </div>
      </div>
      <div class="mbar"><i id="mbi"></i></div>
      <div class="mtime"><span id="mp">0:00</span><span id="md">0:00</span></div>
      <div class="mctl">
        <button class="mbtn" id="mprev" aria-label="上一首">
          <svg viewBox="0 0 24 24"><rect x="5" y="4.8" width="2.4" height="14.4" rx="1.2"/>
            <path d="M18.2 5.2 L8.6 12 L18.2 18.8 Z"/></svg></button>
        <button class="mbtn big" id="mplay" aria-label="播放或暂停"></button>
        <button class="mbtn" id="mnext" aria-label="下一首">
          <svg viewBox="0 0 24 24"><rect x="16.6" y="4.8" width="2.4" height="14.4" rx="1.2"/>
            <path d="M5.8 5.2 L15.4 12 L5.8 18.8 Z"/></svg></button>
      </div>
      <div class="foot">这几个按钮直接控电脑上的播放器，电脑那边会跟着动</div>
    </div>
  </div>

  <!-- ============ 1 情报 ============ -->
  <div class="page" id="pg1">
    <div class="card">
      <div class="lab"><span class="labw"><svg class="dtmark" viewBox="0 0 24 24" fill="none"
        stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 3.2 L21.2 19.4 H2.8 Z"/>
        <path d="M11.9 9.4 L8.3 14.6 H11.3 L10.1 18.6 L13.9 13.4 H10.9 Z"/>
      </svg>三角洲情报</span><span class="hint" id="iat"></span></div>
      <div id="intel"><div class="empty">还没拉数据。点下面的「刷新全部」让电脑去抓一次</div></div>
      <button id="iall" class="ghost">刷新全部</button>
    </div>
  </div>

  <!-- ============ 2 文件 ============ -->
  <div class="page" id="pg2">
    <div class="card">
      <div class="lab"><span>电脑上的文件</span><span class="hint" id="fl"></span></div>
      <div id="files"><div class="empty">还没加载</div></div>
      <button id="ref" class="ghost">刷新列表</button>
      <button id="openloc" class="ghost">在手机里打开「下载」文件夹</button>
    </div>
    <div class="card">
      <div class="lab"><span>传到电脑</span><span class="hint" id="up"></span></div>
      <button id="pick">选择文件（任意类型）</button>
      <input type="file" id="fi" multiple style="display:none">
      <div class="prog" id="pw" style="display:none"><i id="pb"></i></div>
      <div class="foot" id="f2"></div>
    </div>
  </div>

  <!-- ============ 3 剪贴板 ============ -->
  <div class="page" id="pg3">
    <div class="card">
      <div class="lab"><span>电脑剪贴板</span><span class="hint" id="ts"></span></div>
      <pre id="pc">（空）</pre>
      <button id="copy">复制到手机</button>
    </div>
    <div class="card">
      <div class="lab"><span>最近复制过的</span><span class="hint">最多 10 条</span></div>
      <div id="hist"><div class="empty">还没有记录</div></div>
    </div>
    <div class="card">
      <div class="lab"><span>发到电脑</span></div>
      <textarea id="ta" placeholder="粘贴或打字，然后点发送"></textarea>
      <button id="send">发送到电脑</button>
      <button id="grab" class="ghost">读取手机剪贴板并发送</button>
    </div>
  </div>

  <!-- ============ 4 设置 ============ -->
  <div class="page" id="pg4">
    <div class="card">
      <div class="lab"><span>外观</span><span class="hint">整页立刻变</span></div>
      <div class="seg">
        <button data-th="dark" class="on">原版 · 深色</button>
        <button data-th="light">浅色</button>
      </div>
    </div>
    <div class="card">
      <div class="lab"><span>壁纸</span><span class="hint">只存在这台手机上</span></div>
      <div id="wprev" class="wprev empty">还没有壁纸</div>
      <button id="wpick">从相册选一张</button>
      <button id="wclear" class="ghost">去掉壁纸</button>
      <input id="wfile" type="file" accept="image/*" style="display:none">
      <div class="foot">选一张图当整页背景，会自动裁好并压小体积；图只存这台手机上，不占电脑空间。深色/浅色各有一层遮罩，字照样看得清。</div>
    </div>
    <div class="card">
      <div class="lab"><span>液态玻璃</span><span class="hint">卡片带磨砂透感</span></div>
      <div class="seg">
        <button data-gl="1" class="on">开</button>
        <button data-gl="0">关</button>
      </div>
      <div class="foot">关掉之后卡片变成实底，老手机翻页更省力。</div>
    </div>
    <div class="card">
      <div class="lab"><span>关于</span></div>
      <div class="foot" style="margin-top:0">
        数据每秒从电脑上那个采集器取一次；CPU 温度没做，Windows 读不到准数，给假数字不如不给。<br>
        手机和电脑必须连在同一个 WiFi 下，换了网络要重新扫码。
      </div>
    </div>
  </div>
</div>

<div id="msg"></div>

<nav class="nav">
  <button class="on" data-p="0">
    <svg viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round">
      <rect x="4" y="4" width="7" height="7" rx="2"/><rect x="13" y="4" width="7" height="7" rx="2"/>
      <rect x="4" y="13" width="7" height="7" rx="2"/><rect x="13" y="13" width="7" height="7" rx="2"/>
    </svg>状态</button>
  <button data-p="1">
    <svg viewBox="0 0 24 24" fill="none" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 3.2 L21.2 19.4 H2.8 Z"/>
      <path d="M11.9 9.4 L8.3 14.6 H11.3 L10.1 18.6 L13.9 13.4 H10.9 Z"/>
    </svg>三角洲情报</button>
  <button data-p="2">
    <svg viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round">
      <line x1="8" y1="5" x2="8" y2="15"/><line x1="8" y1="15" x2="5" y2="11"/>
      <line x1="8" y1="15" x2="11" y2="11"/>
      <line x1="17" y1="19" x2="17" y2="9"/><line x1="17" y1="9" x2="20" y2="13"/>
      <line x1="17" y1="9" x2="14" y2="13"/>
    </svg>文件</button>
  <button data-p="3">
    <svg viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round">
      <rect x="5" y="4" width="14" height="16" rx="3"/>
      <line x1="9" y1="9" x2="15" y2="9"/><line x1="9" y1="13" x2="15" y2="13"/>
      <line x1="9" y1="17" x2="13" y2="17"/>
    </svg>剪贴板</button>
  <button data-p="4">
    <svg viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round">
      <circle cx="12" cy="12" r="3.2"/>
      <path d="M12 4.2v2.4M12 17.4v2.4M4.2 12h2.4M17.4 12h2.4M6.5 6.5l1.7 1.7M15.8 15.8l1.7 1.7M17.5 6.5l-1.7 1.7M8.2 15.8l-1.7 1.7"/>
    </svg>设置</button>
</nav>

<script>
var T = "@@T@@";
var lastText = null, lastSig = "", lastIntel = null, lastFiles = "init", lastSys = "";
var refreshing = {};
var curPage = 0;
var Q = new URLSearchParams(location.search);
function $(id){return document.getElementById(id)}
var _sayT = 0;
function say(s, c){
  var m = $("msg");
  m.textContent = s;
  m.style.color = c || "var(--fg3)";
  clearTimeout(_sayT);
  /* 提示自己走：10 秒后淡掉，不留到下一次操作 */
  if(s){ _sayT = setTimeout(function(){ m.textContent = ""; m.style.color = ""; }, 10000); }
}
function el(tag, cls, txt){
  var e = document.createElement(tag);
  if(cls) e.className = cls;
  if(txt != null) e.textContent = txt;
  return e;
}
function human(n){
  if(n == null) return "—";
  if(n < 1024) return n + " B";
  if(n < 1048576) return (n / 1024).toFixed(0) + " KB";
  if(n < 1073741824) return (n / 1048576).toFixed(1) + " MB";
  return (n / 1073741824).toFixed(2) + " GB";
}

/* ---------- 外观 ---------- */
function look(){
  var th = localStorage.getItem("fm_theme") || "dark";
  var gl = localStorage.getItem("fm_glass");
  if(gl === null) gl = "1";
  if(Q.get("th")) th = Q.get("th");
  if(Q.get("gl")) gl = Q.get("gl");
  document.body.classList.toggle("light", th === "light");
  document.body.classList.toggle("glass", gl === "1");
  document.querySelectorAll(".seg button[data-th]").forEach(function(b){
    b.classList.toggle("on", b.dataset.th === th);
  });
  document.querySelectorAll(".seg button[data-gl]").forEach(function(b){
    b.classList.toggle("on", b.dataset.gl === gl);
  });
}
document.querySelectorAll(".seg button[data-th]").forEach(function(b){
  b.onclick = function(){
    localStorage.setItem("fm_theme", b.dataset.th);
    if(Q.get("th")){ Q.delete("th"); }
    look();
  };
});
document.querySelectorAll(".seg button[data-gl]").forEach(function(b){
  b.onclick = function(){
    localStorage.setItem("fm_glass", b.dataset.gl);
    if(Q.get("gl")){ Q.delete("gl"); }
    look();
  };
});

/* ---------- 壁纸 ---------- */
function applyWall(url){
  var b = document.body, pv = $("wprev");
  if(url){
    b.style.setProperty("--wall", 'url("' + url + '")');
    b.classList.add("haswall");
    pv.style.backgroundImage = 'url("' + url + '")';
    pv.classList.remove("empty");
    pv.textContent = "";
  }else{
    b.style.removeProperty("--wall");
    b.classList.remove("haswall");
    pv.style.backgroundImage = "";
    pv.classList.add("empty");
    pv.textContent = "还没有壁纸";
  }
}
function shrinkImg(file, maxSide, q, cb){
  var fr = new FileReader();
  fr.onload = function(){
    var img = new Image();
    img.onload = function(){
      var r = Math.min(1, maxSide / Math.max(img.width, img.height));
      var cv = document.createElement("canvas");
      cv.width = Math.max(1, Math.round(img.width * r));
      cv.height = Math.max(1, Math.round(img.height * r));
      cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height);
      cb(cv.toDataURL("image/jpeg", q));
    };
    img.onerror = function(){ say("这张图手机打不开，换一张试试", "var(--warn)"); };
    img.src = fr.result;
  };
  fr.onerror = function(){ say("读不出这张图", "var(--bad)"); };
  fr.readAsDataURL(file);
}
$("wpick").onclick = function(){ $("wfile").click(); };
$("wfile").onchange = function(){
  var f = this.files && this.files[0];
  this.value = "";
  if(!f){ return; }
  say("正在处理…");
  shrinkImg(f, 1400, 0.78, function(u){
    try{
      localStorage.setItem("fm_wall", u);
      applyWall(u);
      say("壁纸换好了", "var(--accent)");
    }catch(e){
      say("这张存不下，换张小点的图", "var(--warn)");
    }
  });
};
$("wclear").onclick = function(){
  localStorage.removeItem("fm_wall");
  applyWall("");
  say("已去掉壁纸");
};
applyWall(localStorage.getItem("fm_wall") || "");

/* ---------- 分页 ---------- */
function gotoPage(i){
  curPage = i;
  document.querySelectorAll(".nav button").forEach(function(x){
    x.classList.toggle("on", +x.dataset.p === i);
  });
  document.querySelectorAll(".page").forEach(function(p, idx){
    p.classList.toggle("on", idx === i);
  });
  $("wrap").scrollTop = 0;
  if(i === 1) loadIntel();
  if(i === 2) loadFiles();
}
document.querySelectorAll(".nav button").forEach(function(b){
  b.onclick = function(){ gotoPage(+b.dataset.p); };
});

/* ---------- 状态 ---------- */
function bar(b, v, warn){
  b.style.width = Math.max(0, Math.min(100, v || 0)) + "%";
  b.style.background = warn ? "linear-gradient(90deg,#ffb454,#ff7a45)"
                            : "linear-gradient(90deg,var(--accent2),var(--accent))";
}
function renderSys(s){
  if(!s) return;
  $("t1").textContent = s.cpu == null ? "—" : Math.round(s.cpu) + "%";
  $("t1").style.color = (s.cpu || 0) >= 85 ? "var(--warn)" : "var(--fg)";
  bar($("b1"), s.cpu, (s.cpu || 0) >= 85);

  $("t2").textContent = s.mem == null ? "—" : Math.round(s.mem) + "%";
  $("t2").style.color = (s.mem || 0) >= 90 ? "var(--warn)" : "var(--fg)";
  bar($("b2"), s.mem, (s.mem || 0) >= 90);
  $("u2").textContent = (s.mem_used != null && s.mem_total != null)
    ? (+s.mem_used).toFixed(1) + " / " + (+s.mem_total).toFixed(1) + " GB" : "";

  if(s.gpu != null){
    $("t3").textContent = Math.round(s.gpu) + "%";
    bar($("b3"), s.gpu, s.gpu >= 95);
    $("u3").textContent = (s.gpu_mem != null && s.gpu_mem_total != null)
      ? "显存 " + (+s.gpu_mem).toFixed(1) + " / " + (+s.gpu_mem_total).toFixed(1) + " GB" : "";
    $("t4").textContent = s.temp == null ? "—" : Math.round(s.temp) + "℃";
    $("u4").textContent = "NVIDIA";
    $("f1").textContent = "";
  }else{
    $("t3").textContent = "—"; $("u3").textContent = "";
    $("t4").textContent = "—"; $("u4").textContent = "";
    $("f1").textContent = "没读到 NVIDIA 显卡（A 卡或核显读不到，不影响其它功能）";
  }
}

/* ---------- 情报 ---------- */
function line(name, value, cls){
  var row = el("div", "line");
  row.appendChild(el("span", "n", name));
  row.appendChild(el("span", "v" + (cls ? " " + cls : ""), value));
  return row;
}
function pwdLine(name, code){
  var row = line(name, code);
  row.className += " pwd";
  row.onclick = function(){ copyText(code); };
  return row;
}
function blk(title, updated, key, rows, more){
  var sec = el("div", "blk");
  var head = el("div", "blkhead");
  head.appendChild(el("span", null, title));
  if(updated) head.appendChild(el("em", null, updated));
  var btn = el("button", "mini", refreshing[key] ? "抓取中…" : "刷新");
  if(refreshing[key]) btn.disabled = true;
  btn.onclick = function(){ intelRefresh(key); };
  head.appendChild(btn);
  sec.appendChild(head);
  rows.forEach(function(r){ sec.appendChild(r); });
  if(more) sec.appendChild(el("div", "foot", more));
  return sec;
}
function renderIntel(d){
  lastIntel = d;
  var box = $("intel");
  box.textContent = "";
  if(!d || !d.ok){
    box.appendChild(el("div", "empty", "电脑那边还没准备好"));
    return;
  }
  var pwd = d.pwd || {}, maps = pwd.maps || {}, names = Object.keys(maps), rows = [];
  names.slice(0, 8).forEach(function(n){ rows.push(pwdLine(n, maps[n])); });
  if(!rows.length) rows.push(el("div", "empty", "还没有今日密码，点刷新让电脑抓一次"));
  box.appendChild(blk("今日密码 · " + (d.codes_date || "?"), pwd.updated || "自动", "pwd", rows, ""));

  var ammo = (d.ammo || {}).list || [];
  rows = [];
  ammo.slice(0, 6).forEach(function(it){ rows.push(line(it.name + "  x" + it.count, it.total + " 币", "g")); });
  if(!rows.length) rows.push(el("div", "empty", "没有数据"));
  box.appendChild(blk("子弹自选包", (d.ammo || {}).updated || "", "ammo", rows,
                      ammo.length > 6 ? "还有 " + (ammo.length - 6) + " 项" : ""));

  var fake = (d.fake || {}).list || [];
  rows = [];
  fake.slice(0, 6).forEach(function(it){
    rows.push(line("#" + it.rank + " " + it.name, "差 " + (it.diff > 0 ? "+" : "") + it.diff,
                   it.diff > 0 ? "g" : "o"));
  });
  if(!rows.length) rows.push(el("div", "empty", "没有数据"));
  box.appendChild(blk("假账榜", (d.fake || {}).updated || "", "fake", rows,
                      fake.length > 6 ? "还有 " + (fake.length - 6) + " 项" : ""));

  var groups = (d.profit || {}).groups || [];
  rows = [];
  groups.slice(0, 3).forEach(function(g){
    rows.push(el("div", "foot", g.station));
    (g.list || []).slice(0, 3).forEach(function(it){
      rows.push(line(it.name + "  " + it.hours + "h", "+" + it.profit, "g"));
    });
  });
  if(!rows.length) rows.push(el("div", "empty", "没有数据"));
  box.appendChild(blk("制造利润", (d.profit || {}).updated || "", "profit", rows, ""));

  $("iat").textContent = d.fetched_at ? "上次抓取 " + d.fetched_at.slice(5, 16) : "";
}
async function loadIntel(){
  try{
    var r = await fetch("/api/intel?t=" + T, {cache: "no-store"});
    var j = await r.json();
    if(j && j.ok) renderIntel(j);
  }catch(e){}
}
async function intelRefresh(key){
  if(refreshing[key]) return;
  refreshing[key] = true;
  renderIntel(lastIntel);
  say("电脑正在抓，稍等…");
  try{
    var r = await fetch("/api/intel_refresh?t=" + T + "&key=" + key, {method: "POST"});
    var j = await r.json();
    if(!j || !j.ok){ refreshing[key] = false; renderIntel(lastIntel); say("电脑正忙着抓别的", "var(--warn)"); return; }
  }catch(e){
    refreshing[key] = false; renderIntel(lastIntel); say("连不上电脑", "var(--bad)"); return;
  }
  var before = JSON.stringify((lastIntel || {})[key]);
  var t0 = Date.now();
  var iv = setInterval(async function(){
    await loadIntel();
    if(JSON.stringify((lastIntel || {})[key]) !== before){
      clearInterval(iv); refreshing[key] = false; renderIntel(lastIntel); say("已更新", "var(--accent)"); return;
    }
    if(Date.now() - t0 > 45000){
      clearInterval(iv); refreshing[key] = false; renderIntel(lastIntel);
      say("等太久了，电脑那边可能没抓到", "var(--warn)");
    }
  }, 1500);
}
$("iall").onclick = function(){
  ["pwd", "ammo", "fake", "profit"].forEach(function(k){ refreshing[k] = false; });
  intelRefresh("pwd");
  setTimeout(function(){ intelRefresh("ammo"); }, 120);
  setTimeout(function(){ intelRefresh("fake"); }, 240);
  setTimeout(function(){ intelRefresh("profit"); }, 360);
};

/* ---------- 文件 ---------- */
function fileIcon(name){
  var ext = (name.split(".").pop() || "").toLowerCase();
  if(["mp4","mkv","mov","avi","webm"].indexOf(ext) >= 0) return "VID";
  if(["png","jpg","jpeg","webp","bmp","gif"].indexOf(ext) >= 0) return "IMG";
  if(["zip","rar","7z"].indexOf(ext) >= 0) return "ZIP";
  if(["exe","msi"].indexOf(ext) >= 0) return "APP";
  if(["txt","md","json","log"].indexOf(ext) >= 0) return "TXT";
  return "FILE";
}
async function loadFiles(){
  try{
    var r = await fetch("/api/files?t=" + T, {cache: "no-store"});
    var j = await r.json();
    if(!j || !j.ok) return;
    $("f2").textContent = "手机传上来的会存在电脑的「收到」文件夹里";
    var sig = (j.items || []).map(function(f){ return f.name + f.size; }).join("|");
    if(sig === lastFiles) return;
    lastFiles = sig;
    var box = $("files");
    box.textContent = "";
    var items = j.items || [];
    $("fl").textContent = items.length ? items.length + " 个文件" : "";
    var sf1 = $("sf1");
    if(sf1) sf1.textContent = items.length
      ? "「分享」里 " + items.length + " 个文件等着你下"
      : "电脑上点「选文件发给手机」，或者丢进「分享」文件夹";
    if(!items.length){
      box.appendChild(el("div", "empty", "「分享」还是空的。电脑上点「选文件发给手机」，挑什么类型都行，再点刷新"));
      return;
    }
    items.forEach(function(f){
      var row = el("div", "fitem");
      row.appendChild(el("div", "fico", fileIcon(f.name)));
      var mid = el("div", "fname");
      var nm = el("div", "fn", f.name);
      nm.title = f.name;
      mid.appendChild(nm);
      mid.appendChild(el("div", "fm", human(f.size) + "　" + (f.time || "")));
      row.appendChild(mid);
      var a = el("a", null, "下载");
      a.href = "/api/file?t=" + T + "&name=" + encodeURIComponent(f.name);
      a.setAttribute("download", f.name);
      row.appendChild(a);
      box.appendChild(row);
    });
  }catch(e){ say("拉文件列表失败", "var(--bad)"); }
}
$("ref").onclick = function(){ lastFiles = ""; loadFiles(); say("已刷新"); };
$("openloc").onclick = function(){
  try{
    if(window.FlintNative && window.FlintNative.openDownloads){
      window.FlintNative.openDownloads();
      say("已跳到手机的「下载」文件夹");
    }else{
      say("这台手机的 App 还是旧版，更新一下就能直接跳过去", "var(--warn)");
    }
  }catch(e){ say("跳不过去：拿文件管理看「下载」目录", "var(--warn)"); }
};

$("pick").onclick = function(){ $("fi").click(); };
$("fi").onchange = function(){
  var fs = $("fi").files;
  if(!fs || !fs.length) return;
  var list = [];
  for(var i = 0; i < fs.length; i++) list.push(fs[i]);
  $("fi").value = "";
  uploadAll(list);
};

function uploadOne(file, idx, total){
  return new Promise(function(resolve){
    var xhr = new XMLHttpRequest();
    var url = "/api/upload?t=" + T + "&name=" + encodeURIComponent(file.name);
    xhr.open("POST", url);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    var t0 = Date.now();
    xhr.upload.onprogress = function(e){
      if(!e.lengthComputable) return;
      var pct = e.loaded / e.total * 100;
      $("pb").style.width = pct + "%";
      var sec = (Date.now() - t0) / 1000;
      var speed = sec > 0.5 ? e.loaded / sec : 0;
      $("up").textContent = "第 " + (idx + 1) + "/" + total + " 个　" +
        pct.toFixed(0) + "%　" + human(e.loaded) + " / " + human(e.total) +
        (speed ? "　" + human(speed) + "/s" : "");
    };
    xhr.onload = function(){
      var ok = false, j = null;
      try{ j = JSON.parse(xhr.responseText); ok = !!(j && j.ok); }catch(e){}
      if(!ok){
        say((j && (j.why === "space" ? "电脑硬盘不够了" : "电脑那边没收下")) || "上传失败", "var(--bad)");
      }
      resolve(ok);
    };
    xhr.onerror = function(){ say("传到一半断了，确认还在同一个 WiFi", "var(--bad)"); resolve(false); };
    xhr.send(file);
  });
}

async function uploadAll(list){
  $("pw").style.display = "";
  $("pb").style.width = "0";
  var done = 0;
  for(var i = 0; i < list.length; i++){
    var ok = await uploadOne(list[i], i, list.length);
    if(ok) done++;
  }
  $("pw").style.display = "none";
  $("up").textContent = "";
  say(done === list.length ? "全部传完了，共 " + done + " 个" : "传完 " + done + " / " + list.length + " 个",
      done === list.length ? "var(--accent)" : "var(--warn)");
}

/* ---------- 剪贴板 ---------- */
function fillBox(t){
  var ta = $("ta"); ta.value = t; ta.focus();
  try{ ta.setSelectionRange(0, t.length); }catch(e){}
}
async function copyText(t){
  if(!t || !t.trim()){ say("这条是空的", "var(--warn)"); return; }
  try{
    if(!navigator.clipboard || !navigator.clipboard.writeText){ throw new Error("no api"); }
    await navigator.clipboard.writeText(t);
    say("已复制到手机剪贴板", "var(--accent)");
  }catch(e){
    fillBox(t);
    say("这台浏览器不许网页直接写剪贴板，已填到下面的框里并选中，长按「复制」即可", "var(--warn)");
  }
}
function renderHistory(list){
  var box = $("hist");
  box.textContent = "";
  if(!list || !list.length){
    box.appendChild(el("div", "empty", "还没有记录"));
    return;
  }
  list.forEach(function(item){
    var row = el("div", "row");
    var txt = el("div", "txt");
    txt.textContent = (item.text || "").replace(/\s+/g, " ");
    txt.title = (item.text || "") + "  " + (item.time || "");
    row.appendChild(txt);
    var btn = el("button", "mini2", "复制");
    btn.onclick = function(){ copyText(item.text); };
    row.appendChild(btn);
    var del = el("button", "mini2 x", "\u00d7");
    del.title = "从电脑那边的历史里删掉这条";
    del.onclick = async function(){
      try{
        var r = await fetch("/api/del?id=" + item.id + "&t=" + T, {method: "POST"});
        var j = await r.json();
        if(j && j.ok){ lastSig = ""; await pull(); say("已删掉这条"); }
      }catch(e){ say("删不掉，可能已经断开了", "var(--bad)"); }
    };
    row.appendChild(del);
    box.appendChild(row);
  });
}
async function pull(){
  try{
    var r = await fetch("/api/pull?t=" + T, {cache: "no-store"});
    var j = await r.json();
    if(!j || !j.ok) return;
    $("dot").className = "dot on";
    renderSys(j.sys);
    if(j.music) renderMusic(j.music);
    if(j.clip === false){
      if(lastText !== "__off__"){
        lastText = "__off__";
        $("pc").textContent = "电脑那边把剪贴板关掉了（设置 → 手机 · 剪贴板）";
        $("ts").textContent = "已关闭";
        lastSig = "";
        renderHistory([]);
      }
      return;
    }
    var t = j.text || "";
    if(t !== lastText){
      lastText = t;
      $("pc").textContent = t || "（空）";
      $("ts").textContent = t ? "已同步" : "";
    }
    var hist = j.history || [];
    var sig = hist.map(function(h){ return h.id + "|" + h.time + "|" + h.text; }).join("\n");
    if(sig !== lastSig){ lastSig = sig; renderHistory(hist); }
  }catch(e){
    $("dot").className = "dot";
    $("ts").textContent = "连不上";
  }
}
$("copy").onclick = function(){ copyText($("pc").textContent); };
async function push(t){
  if(!t || !t.trim()){ say("没有内容可发", "var(--warn)"); return false; }
  try{
    var r = await fetch("/api/push?t=" + T, {method: "POST", body: t});
    var j = await r.json();
    if(j && j.ok){ say("已发到电脑剪贴板", "var(--accent)"); $("ta").value = ""; return true; }
    say("没发出去", "var(--bad)"); return false;
  }catch(e){ say("连不上电脑，确认两边是同一个 WiFi", "var(--bad)"); return false; }
}
$("send").onclick = function(){ push($("ta").value); };
$("grab").onclick = async function(){
  try{
    var t = await navigator.clipboard.readText();
    await push(t);
  }catch(e){
    say("浏览器不许读剪贴板，请长按下面框粘贴，再点发送", "var(--warn)");
    $("ta").focus();
  }
};

/* ---------- 音乐 ---------- */
function mmss(ms){
  ms = Math.max(0, ms || 0);
  var s = Math.floor(ms / 1000);
  return Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2);
}
var lastMusic = "";
function playIcon(playing){
  $("mplay").innerHTML = playing
    ? '<svg viewBox="0 0 24 24"><rect x="6.2" y="4.4" width="3.8" height="15.2" rx="1.5"/>'
      + '<rect x="14" y="4.4" width="3.8" height="15.2" rx="1.5"/></svg>'
    : '<svg viewBox="0 0 24 24"><path d="M7.4 4.2 L20 12 L7.4 19.8 Z"/></svg>';
}
function renderMusic(m){
  if(!m) return;
  var t = m.title || "";
  $("mt").textContent = t || "没在放歌";
  $("ma").textContent = m.artist || (t ? "" : "先在电脑的音乐页里点一首");
  $("mhint").textContent = t ? (m.playing ? "正在播放" : "已暂停") : "空闲";
  $("mp").textContent = mmss(m.pos);
  $("md").textContent = mmss(m.dur);
  $("mbi").style.width = (m.dur > 0 ? Math.min(100, 100 * m.pos / m.dur) : 0) + "%";
  var cov = $("mcov");
  if(m.cover){
    cov.style.backgroundImage = 'url("' + m.cover + '")';
  }else{
    cov.style.backgroundImage = "";
  }
  var sig = t + "|" + (m.playing ? 1 : 0);
  if(sig !== lastMusic){ playIcon(!!m.playing); lastMusic = sig; }
  var has = !!t;
  ["mprev", "mplay", "mnext"].forEach(function(id){ $(id).disabled = !has; });
}
async function musicCmd(cmd){
  try{
    var r = await fetch("/api/music?t=" + T + "&cmd=" + cmd, {method: "POST"});
    var d = await r.json();
    if(!d || !d.ok){ say((d && d.why) || "电脑没接住这条命令", "var(--warn)"); return; }
    if(d.state) renderMusic(d.state);
  }catch(e){ say("连不上电脑", "var(--bad)"); }
}
$("mprev").onclick = function(){ musicCmd("prev"); };
$("mplay").onclick = function(){ musicCmd("toggle"); };
$("mnext").onclick = function(){ musicCmd("next"); };
playIcon(false);

look();
pull();
setInterval(pull, 2000);
if(Q.get("pg")) gotoPage(+Q.get("pg"));

/* ---- 断线自检：每隔 2.5 秒问一次电脑还在不在，没应答就出遮罩 ---- */
(function () {
  var el = document.getElementById("clinlost");
  if (!el) return;
  var hint = document.getElementById("losthint");
  var fails = 0;
  var shown = false;

  function show() {
    if (shown) return;
    shown = true;
    el.classList.add("on");
  }
  function hide() {
    if (!shown) return;
    shown = false;
    el.classList.remove("on");
  }

  async function ping() {
    try {
      var r = await fetch("/api/info?t=" + T, { cache: "no-store" });
      if (!r.ok) throw new Error("http" + r.status);
      await r.json();
      if (fails) {
        fails = 0;
        hide();
        if (typeof say === "function") say("已经连回来了");
      }
    } catch (e) {
      fails++;
      if (fails >= 1) {
        show();
        if (hint) {
          hint.textContent = fails === 1
            ? "第 1 次没连上，正在自动重试…"
            : "已经试了 " + fails + " 次，还是没连上";
        }
      }
    }
  }

  var btn1 = document.getElementById("lostretry");
  var btn2 = document.getElementById("lostother");
  if (btn1) btn1.onclick = function () { location.reload(); };
  if (btn2) btn2.onclick = function () {
    if (window.FlintNative && window.FlintNative.openConnect) {
      window.FlintNative.openConnect();
    } else {
      alert("App 还是旧版：先按手机的返回键回到连接页，再点「重新连接别的电脑」。装新版 App 后这里能一键回去。");
    }
  };

  setInterval(ping, 2500);
  ping();
})();
</script>
</body></html>
'''


def _lan_ip() -> str:
    """拿本机在局域网里的地址。连一个公网 IP（不发包）只是为了问出出口网卡。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    finally:
        s.close()
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return ""


def _new_token() -> str:
    return "".join(secrets.choice("0123456789abcdef") for _ in range(12))


def qr_pixmap(url: str, scale: int = 7):
    """把地址做成二维码位图。缺 segno 就返回 None，由界面提示。"""
    try:
        import segno
    except ImportError:
        return None
    from PySide6 import QtGui

    buf = io.BytesIO()
    segno.make(url, error="m").save(
        buf, kind="png", scale=scale, border=2, dark="#0b0f14", light="#ffffff"
    )
    pm = QtGui.QPixmap()
    pm.loadFromData(buf.getvalue(), "PNG")
    return pm if not pm.isNull() else None


def _app_dir() -> Path:
    from core.store import app_dir

    return app_dir()


def _safe_name(raw: str) -> str:
    """只留文件名本身，挡掉 ../ 之类的路径穿越。"""
    name = os.path.basename((raw or "").replace("\\", "/")).strip()
    name = "".join(c for c in name if c not in '<>:"|?*\r\n\t')
    return name[:120]


CREATE_NO_WINDOW = 0x08000000
FW_RULE_OLD = "燧镜剪贴板"          # 第一版：只放行专用网络，家用 WiFi 被标"公用"时会失效
FW_RULE = "燧镜剪贴板-local"        # 第二版：按同子网放行，跟网络类别无关
FW_RULE_UDP = "燧镜剪贴板-local-udp"  # 同一条思路，专给「自动发现」用的 UDP
FW_PORTS = "8848,8850,8852,8860,8870"
FW_DISC = "8849"                    # App 广播找电脑的口；少了这条规则，手机永远发现不到电脑


def _rule_exists(name: str) -> bool:
    """这条规则在不在。查询不需要管理员权限。"""
    try:
        r = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"],
            capture_output=True,
            timeout=8,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return True  # 查不出来就别拿这个吓唬人
    return r.returncode == 0


def firewall_ok() -> bool:
    """TCP 和 UDP 两条都得在。

    只查 TCP 是之前那个坑：网页能连、配对能通，但手机的「自动发现」一直在门口被挡，
    表现就是「自动发现电脑从来没连上过」。
    """
    return _rule_exists(FW_RULE) and _rule_exists(FW_RULE_UDP)


def allow_firewall() -> tuple[bool, str]:
    """加一条「仅同一子网可入」的放行规则。要 UAC，用户点「是」才生效。

    为什么不按网络类别放行：Windows 常把家里的 WiFi 标成「公用网络」，
    那种情况下只放行「专用」的规则等于没放行。改成按子网限定，
    不管是公用还是专用都能连，而外面的机器还是进不来。
    """
    lines = [
        "@echo off",
        f'netsh advfirewall firewall delete rule name="{FW_RULE_OLD}" >nul 2>&1',
        f'netsh advfirewall firewall delete rule name="{FW_RULE}" >nul 2>&1',
        f'netsh advfirewall firewall delete rule name="{FW_RULE_UDP}" >nul 2>&1',
        (
            f'netsh advfirewall firewall add rule name="{FW_RULE}" dir=in action=allow '
            f"protocol=TCP localport={FW_PORTS} profile=any remoteip=localsubnet"
        ),
        (
            f'netsh advfirewall firewall add rule name="{FW_RULE_UDP}" dir=in action=allow '
            f"protocol=UDP localport={FW_DISC} profile=any remoteip=localsubnet"
        ),
    ]
    bat = os.path.join(tempfile.gettempdir(), "flint_fw.bat")
    try:
        # 中文规则名用 GBK 写，cmd 默认代码页是 936
        with open(bat, "w", encoding="gbk", newline="\r\n") as fh:
            fh.write("\r\n".join(lines) + "\r\n")
    except OSError as exc:
        return False, "写不了临时脚本：" + str(exc)
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "cmd.exe", f'/c "{bat}"', None, 0
        )
    except Exception as exc:  # noqa: BLE001
        return False, "叫不起来提权：" + str(exc)
    if rc == 5:
        return False, "你点了取消，规则没加上"
    if rc <= 32:
        return False, f"提权失败（{rc}）"
    return True, "已经弹了管理员确认，点「是」之后手机就能连上了"


class LanBridge(QtCore.QObject):
    """电脑这一侧：剪贴板 + 电脑状态 + 三角洲情报 + 文件互传，跑一个只认 token 的小服务。"""

    pushed = QtCore.Signal(str)             # 手机发来的文字
    intel_refresh_ask = QtCore.Signal(str)  # 手机想刷新某一块情报
    music_ask = QtCore.Signal(str)          # 手机要控电脑上的播放器
    link = QtCore.Signal(bool, str)         # 手机连上 / 断开，后面跟一句"哪台机器"

    LINK_IDLE = 8.0                          # 手机每 2.5 秒 ping 一次，8 秒没动静就算断了
    PAIR_TTL = 300                           # 配对码管用多久（秒）
    PAIR_MAX_FAILS = 5                       # 同一个码连错这么多次就作废换新
    DISC_PORT = 8849                         # 手机那头发 UDP 广播找电脑，听这个口

    def __init__(self, token: str = "", parent=None) -> None:
        super().__init__(parent)
        self._text = ""
        self._history: list[dict] = []
        self._seq = 0
        self._token = token if isinstance(token, str) and token else _new_token()
        self._lan_id = ""            # 这台机器的身份，由主窗口塞进来
        self._srv = None
        self._port = 0
        self.sys_provider = None     # 无参，返回电脑状态 dict
        self.intel_provider = None   # 无参，返回三角洲情报 dict
        self.recv_dir_provider = None  # 无参，返回用户自定义的接收目录（空=默认）
        self._music: dict = {}       # 主线程写、手机端轮询读
        self._pair_code = ""         # 手机 App 配对用，一次性
        self._pair_until = 0.0
        self._pair_fails = 0         # 这个码被猜错的次数，满 PAIR_MAX_FAILS 就换
        self._last_seen = 0.0        # 最后一次心跳（手机 ping 一下就是一次）
        self._last_ip = ""
        self._last_dev = ""
        self._link_on = False
        self._link_timer = QtCore.QTimer(self)
        self._link_timer.setInterval(2000)
        self._link_timer.timeout.connect(self._poll_link)
        self.clip_provider = None    # 无参，返回剪贴板开关是否启用

    # ---------------------------------------------------------------- 状态
    @property
    def token(self) -> str:
        return self._token

    @property
    def lan_id(self) -> str:
        return self._lan_id

    @lan_id.setter
    def lan_id(self, v: str) -> None:
        self._lan_id = str(v or "")[:40]

    @property
    def text(self) -> str:
        return self._text

    @property
    def history(self) -> list[dict]:
        return list(self._history)

    @property
    def running(self) -> bool:
        return self._srv is not None

    @property
    def port(self) -> int:
        return self._port

    def sys(self) -> dict:
        if not self.sys_provider:
            return {}
        try:
            return self.sys_provider()
        except Exception:  # noqa: BLE001
            return {}

    def set_music(self, state: dict) -> None:
        self._music = state or {}

    def music(self) -> dict:
        return self._music

    def intel(self) -> dict:
        if not self.intel_provider:
            return {"ok": False}
        try:
            return self.intel_provider()
        except Exception:  # noqa: BLE001
            return {"ok": False}

    @property
    def share_dir(self) -> Path:
        d = _app_dir() / SHARE_NAME
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return d

    @property
    def recv_root(self) -> Path:
        custom = ""
        if self.recv_dir_provider is not None:
            try:
                custom = (self.recv_dir_provider() or "").strip()
            except Exception:  # noqa: BLE001
                custom = ""
        d = Path(custom) if custom else _app_dir() / RECV_NAME
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return d

    def open_recv_dir(self) -> bool:
        try:
            os.startfile(str(self.recv_root))
            return True
        except Exception:  # noqa: BLE001
            return False

    def recv_dir(self) -> Path:
        d = self.recv_root / time.strftime("%Y-%m-%d")
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return d

    def list_share(self) -> list[dict]:
        out = []
        try:
            for p in sorted(self.share_dir.iterdir(), key=lambda x: -_mtime(x))[:FILE_LIST_MAX]:
                if not p.is_file():
                    continue
                st = p.stat()
                out.append(
                    {
                        "name": p.name,
                        "size": st.st_size,
                        "time": time.strftime("%m-%d %H:%M", time.localtime(st.st_mtime)),
                    }
                )
        except OSError:
            pass
        return out

    def open_share_dir(self) -> bool:
        try:
            os.startfile(str(self.share_dir))
            return True
        except Exception:  # noqa: BLE001
            return False

    def set_text(self, text: str) -> None:
        text = text or ""
        self._text = text
        if not text.strip():
            return None
        self._history = [h for h in self._history if h["text"] != text]
        self._seq += 1
        self._history.insert(
            0, {"id": self._seq, "text": text, "time": time.strftime("%H:%M")}
        )
        self._history[HIST_MAX:] = []

    def del_history(self, hid: int) -> int:
        self._history = [h for h in self._history if h.get("id") != hid]
        return len(self._history)

    def clip_enabled(self) -> bool:
        if self.clip_provider is None:
            return True
        try:
            return bool(self.clip_provider())
        except Exception:  # noqa: BLE001
            return True

    # ---------------------------------------------------------------- 配对码
    def pair_code(self, refresh: bool = False) -> str:
        now = time.time()
        if refresh or not self._pair_code or now > self._pair_until:
            self._pair_code = "%06d" % secrets.randbelow(1000000)
            self._pair_until = now + self.PAIR_TTL
            self._pair_fails = 0
        return self._pair_code

    def pair_left(self) -> int:
        return max(0, int(self._pair_until - time.time()))

    def check_pair(self, code: str) -> bool:
        """配对码核对。连错 5 次直接作废换新码：6 位数字不设次数上限，同网是能被暴力试穿的。"""
        if time.time() > self._pair_until:
            return False
        code = (code or "").strip()
        if code and code == self._pair_code:
            self._pair_fails = 0
            return True
        self._pair_fails += 1
        if self._pair_fails >= self.PAIR_MAX_FAILS:
            self._pair_code = ""
            self._pair_until = 0.0
            self._pair_fails = 0
        return False

    def consume_pair(self) -> None:
        self._pair_until = 0.0
        self._pair_code = ""

    def qr_text(self) -> str:
        ip = _lan_ip()
        if not ip or not self._port:
            return ""
        return "flint://pair?h=%s&p=%d&c=%s" % (ip, self._port, self.pair_code())

    # ---------------------------------------------------------------- 找电脑
    def _discover_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", self.DISC_PORT))
        except OSError:
            sock.close()
            return
        sock.settimeout(0.4)
        while self._srv is not None:
            try:
                data, addr = sock.recvfrom(128)
            except socket.timeout:
                continue
            except OSError:
                break
            if data.strip().upper() != b"FLINT?":
                continue
            info = {
                "app": "flint",
                "name": socket.gethostname(),
                "ip": _lan_ip(),
                "port": self._port,
            }
            try:
                sock.sendto(json.dumps(info, ensure_ascii=False).encode("utf-8"), addr)
            except OSError:
                continue
        sock.close()

    def url(self) -> str:
        ip = _lan_ip()
        if not ip or not self._port:
            return ""
        return f"http://{ip}:{self._port}/?t={self._token}"

    # ---------------------------------------------------------------- 连着没有
    def touch(self, ip: str = "", ua: str = "") -> None:
        """带对 token 的请求就算一次心跳，顺手记下是哪台手机。"""
        self._last_seen = time.time()
        if ip:
            self._last_ip = ip
        dev = _pretty_device(ua)
        if dev:
            self._last_dev = dev

    @property
    def last_ip(self) -> str:
        """手机那边最后一次连过来的 IP —— 投屏无线直接用它，不让人再手输。"""
        return self._last_ip or ""

    def link_info(self) -> tuple[bool, str]:
        """界面开局先问一句：现在连着吗、对面是哪台。"""
        who = " · ".join([x for x in (self._last_dev, self._last_ip) if x])
        return self._link_on, who

    def _poll_link(self) -> None:
        on = bool(self._srv is not None and (time.time() - self._last_seen) < self.LINK_IDLE)
        if on == self._link_on:
            return
        self._link_on = on
        who = ""
        if on:
            who = " · ".join([x for x in (self._last_dev, self._last_ip) if x])
        self.link.emit(on, who)

    def start(self) -> tuple[bool, str]:
        if self._srv is not None:
            return True, "已经在跑"
        ip = _lan_ip()
        if not ip:
            return False, "没连上局域网（WiFi 或网线都没通？）"
        self.share_dir  # 顺手把目录建出来
        handler = _make_handler(self)
        last_err = ""
        srv = None
        for port in (8848, 8850, 8852, 8860, 8870):
            try:
                srv = ThreadingHTTPServer(("0.0.0.0", port), handler)
                break
            except OSError as exc:
                last_err = str(exc)
                continue
        if srv is None:
            return False, "端口都被占用了：" + last_err
        srv.daemon_threads = True
        self._srv = srv
        self._port = srv.server_address[1]
        threading.Thread(
            target=srv.serve_forever, kwargs={"poll_interval": 0.3}, daemon=True
        ).start()
        threading.Thread(target=self._discover_loop, daemon=True).start()
        self._last_seen = 0.0
        self._link_timer.start()
        return True, f"已开启（{ip}:{self._port}）"

    def stop(self) -> None:
        srv, self._srv = self._srv, None
        self._port = 0
        try:
            self._link_timer.stop()
        except Exception:  # noqa: BLE001
            pass
        if self._link_on:
            self._link_on = False
            self.link.emit(False, "")
        if srv is not None:
            threading.Thread(target=srv.shutdown, daemon=True).start()


_DEV_RE = re.compile(r"\(([^)]*)\)")


def _pretty_device(ua: str) -> str:
    """从 UA 里挑一段像机型的：安卓 WebView 一般写成 "(Linux; Android 13; Mi 13U; wv)"。"""
    m = _DEV_RE.search(ua or "")
    if not m:
        return ""
    bits = [b.strip() for b in m.group(1).split(";") if b.strip()]
    skip = ("linux", "android", "wv", "khtml", "mobile", "like gecko", "u;")
    for b in reversed(bits):
        low = b.lower()
        if low.startswith(skip):
            continue
        if low.isdigit():
            continue
        if "build/" in low:
            b = b.split("Build/")[0].strip()
        if b:
            return b[:24]
    return ""


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _make_handler(bridge: LanBridge):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FlintMirror"
        protocol_version = "HTTP/1.1"  # 大文件要靠长连接，不然每个分块都要重连

        def log_message(self, *args) -> None:  # 别往控制台喷访问日志
            pass

        def _send(self, code: int, body: bytes, ctype: str = "text/plain; charset=utf-8") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if code >= 400:
                self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass

        def _q(self, key: str) -> str:
            return (parse_qs(urlsplit(self.path).query).get(key) or [""])[0]

        def _tok(self) -> str:
            return self._q("t")

        def _ok(self) -> bool:
            tok = self._tok()
            ok = bool(tok) and tok == bridge.token
            if ok:
                bridge.touch(self.client_address[0], self.headers.get("User-Agent", ""))
            return ok

        # -------------------------------------------------------- 下载
        def _send_file(self, path: Path) -> None:
            size = path.stat().st_size
            rng = self.headers.get("Range") or ""
            start, end = 0, size - 1
            if rng.startswith("bytes="):
                part = rng[6:].split("-", 1)
                try:
                    if part[0].strip():
                        start = int(part[0])
                    if len(part) > 1 and part[1].strip():
                        end = int(part[1])
                except ValueError:
                    start, end = 0, size - 1
            if start >= size or start < 0:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            end = min(end, size - 1)
            length = end - start + 1
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(206 if rng else 200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            if rng:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            ext = path.name.rsplit(".", 1)[1] if "." in path.name else ""
            ascii_name = path.name.encode("ascii", "ignore").decode() or ""
            stem = ascii_name.rsplit(".", 1)[0] if "." in ascii_name else ascii_name
            # 整条名字都是中文时 ascii 只剩扩展名的点，兜底成 flint.扩展名
            if not stem.strip("_ ."):
                ascii_name = "flint" + ("." + ext if ext else "")
            self.send_header(
                "Content-Disposition",
                'attachment; filename="%s"; filename*=UTF-8\'\'%s'
                % (ascii_name, quote(path.name)),
            )
            self.end_headers()
            try:
                with open(path, "rb") as fh:
                    fh.seek(start)
                    left = length
                    while left > 0:
                        chunk = fh.read(min(CHUNK, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except OSError:
                pass

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path in ("/", "/index.html"):
                if not self._ok():
                    self._send(403, "链接不对，回电脑上重新扫一下二维码。".encode("utf-8"))
                    return
                html = PAGE.replace("@@T@@", self._tok())
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/favicon.ico":
                self._send(204, b"")
                return
            if path == "/api/info":
                self._ok()  # 手机每 2.5 秒 ping 这个：token 对得上才记成心跳
                body = json.dumps(
                    {
                        "ok": True,
                        "app": "flint",
                        "name": socket.gethostname(),
                        "id": bridge.lan_id,
                        "port": bridge.port,
                        "pair": bool(bridge.pair_code),
                        "left": bridge.pair_left(),
                    },
                    ensure_ascii=False,
                )
                self._send(200, body.encode("utf-8"), "application/json")
                return
            if path == "/api/pair":
                if not bridge.check_pair(self._q("code")):
                    self._send(200, b'{"ok":false,"why":"code"}', "application/json")
                    return
                bridge.consume_pair()
                body = json.dumps(
                    {"ok": True, "token": bridge.token, "port": bridge.port},
                    ensure_ascii=False,
                )
                self._send(200, body.encode("utf-8"), "application/json")
                return
            if not self._ok():
                self._send(403, b'{"ok":false}', "application/json")
                return
            if path == "/api/pull":
                body = json.dumps(
                    {
                        "ok": True,
                        "text": bridge.text,
                        "history": bridge.history,
                        "sys": bridge.sys(),
                        "music": bridge.music(),
                        "clip": bridge.clip_enabled(),
                    },
                    ensure_ascii=False,
                )
                self._send(200, body.encode("utf-8"), "application/json")
                return
            if path == "/api/music":
                body = json.dumps(
                    {"ok": True, "state": bridge.music()}, ensure_ascii=False
                )
                self._send(200, body.encode("utf-8"), "application/json")
                return
            if path == "/api/intel":
                body = json.dumps(bridge.intel(), ensure_ascii=False)
                self._send(200, body.encode("utf-8"), "application/json")
                return
            if path == "/api/files":
                body = json.dumps(
                    {
                        "ok": True,
                        "items": bridge.list_share(),
                        "recv_dir": str(bridge.recv_root),
                    },
                    ensure_ascii=False,
                )
                self._send(200, body.encode("utf-8"), "application/json")
                return
            if path == "/api/file":
                name = _safe_name(self._q("name"))
                target = bridge.share_dir / name
                if not name or not target.is_file():
                    self._send(404, b"not found")
                    return
                self._send_file(target)
                return
            self._send(404, b"not found")

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if not self._ok():
                self._send(403, b'{"ok":false}', "application/json")
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0

            if path == "/api/push":
                if length > MAX_TEXT:  # 剪贴板文字，不是传文件
                    self._send(413, b'{"ok":false}', "application/json")
                    return
                raw = self.rfile.read(length) if length else b""
                text = raw.decode("utf-8", "replace")
                if not text.strip():
                    self._send(200, b'{"ok":false,"why":"empty"}', "application/json")
                    return
                bridge.pushed.emit(text)
                self._send(200, b'{"ok":true}', "application/json")
                return

            if path == "/api/del":
                try:
                    hid = int(self._q("id") or 0)
                except ValueError:
                    hid = 0
                left = bridge.del_history(hid)
                body = json.dumps({"ok": True, "left": left}, ensure_ascii=False)
                self._send(200, body.encode("utf-8"), "application/json")
                return

            if path == "/api/music":
                cmd = self._q("cmd") or "toggle"
                if cmd not in ("toggle", "next", "prev"):
                    self._send(200, b'{"ok":false,"why":"cmd"}', "application/json")
                    return
                if length:
                    self._drain(length)
                bridge.music_ask.emit(cmd)
                body = json.dumps(
                    {"ok": True, "state": bridge.music()}, ensure_ascii=False
                )
                self._send(200, body.encode("utf-8"), "application/json")
                return

            if path == "/api/intel_refresh":
                key = self._q("key") or "pwd"
                if key not in ("pwd", "ammo", "fake", "profit"):
                    self._send(200, b'{"ok":false,"why":"key"}', "application/json")
                    return
                bridge.intel_refresh_ask.emit(key)
                self._send(200, b'{"ok":true}', "application/json")
                return

            if path == "/api/upload":
                self._recv_file(length)
                return

            self._send(404, b"not found")

        # -------------------------------------------------------- 上传
        def _recv_file(self, length: int) -> None:
            name = _safe_name(self._q("name"))
            if not name or length <= 0:
                self._send(200, b'{"ok":false,"why":"name"}', "application/json")
                return
            folder = bridge.recv_dir()
            try:
                free = shutil.disk_usage(str(folder)).free
            except OSError:
                free = 1 << 40
            if length > free - MIN_FREE:
                # 不读 body 直接拒会打断连接，先把手里的数据丢完再回
                self._drain(length)
                self._send(200, b'{"ok":false,"why":"space"}', "application/json")
                return

            target = folder / name
            if target.exists():  # 重名就别覆盖，加个序号
                stem, suffix = os.path.splitext(name)
                for i in range(1, 500):
                    cand = folder / f"{stem}({i}){suffix}"
                    if not cand.exists():
                        target = cand
                        break

            written = 0
            try:
                with open(target, "wb") as fh:
                    left = length
                    while left > 0:
                        chunk = self.rfile.read(min(CHUNK, left))
                        if not chunk:
                            break
                        fh.write(chunk)
                        left -= len(chunk)
                        written += len(chunk)
            except OSError as exc:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
                self._send(200, json.dumps(
                    {"ok": False, "why": str(exc)[:40]}, ensure_ascii=False
                ).encode("utf-8"), "application/json")
                return

            if written != length:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
                self._send(200, b'{"ok":false,"why":"cut"}', "application/json")
                return

            body = json.dumps(
                {"ok": True, "name": target.name, "size": written, "dir": str(folder)},
                ensure_ascii=False,
            )
            self._send(200, body.encode("utf-8"), "application/json")

        def _drain(self, length: int) -> None:
            """把没读的 body 丢掉，不然客户端会卡在写。"""
            left = length
            while left > 0:
                chunk = self.rfile.read(min(CHUNK, left))
                if not chunk:
                    return
                left -= len(chunk)

    return Handler
