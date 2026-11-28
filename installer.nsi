Unicode true
SetCompressor /SOLID lzma
SetCompressorDictSize 64

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"

!define APP_NAME "燧镜"
!define APP_VER "1.12.5"
!define APP_VER4 "1.12.5.0"
!define APP_EXE "燧镜.exe"
!define PUBLISHER "布鲁托是小馋猫"
!define SRC_DIR "分发版\燧镜"
!define REG_UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\燧镜"

Name "${APP_NAME}"
OutFile "燧镜_v1.12.5_安装包.exe"
InstallDir "$LOCALAPPDATA\Programs\燧镜"
InstallDirRegKey HKCU "Software\燧镜" "InstallDir"
RequestExecutionLevel user

Icon "assets\icon.ico"
UninstallIcon "assets\icon.ico"

VIProductVersion "1.12.5.0"
VIAddVersionKey "ProductName" "燧镜"
VIAddVersionKey "CompanyName" "${PUBLISHER}"
VIAddVersionKey "FileDescription" "燧镜 安装程序"
VIAddVersionKey "FileVersion" "${APP_VER4}"
VIAddVersionKey "ProductVersion" "${APP_VER4}"
VIAddVersionKey "LegalCopyright" "${PUBLISHER}"

!define MUI_ABORTWARNING
!define MUI_ICON "assets\icon.ico"
!define MUI_UNICON "assets\icon.ico"
!define MUI_WELCOMEPAGE_TITLE "燧镜 安装"
!define MUI_WELCOMEPAGE_TEXT "燧镜：三角洲分辨率一键切换、截图录屏回放、ACE 限流、系统监控、模组启动框架。$\r$\n$\r$\n安装不需要管理员权限，素材默认就存在程序目录里，能直接写。$\r$\n$\r$\n下一步选安装位置。"
!define MUI_DIRECTORYPAGE_TEXT_TOP "装到哪里。换个盘就点「浏览」。$\r$\n$\r$\n注意：屏幕上的素材、录像、配置都会跟着这个目录走；以后想单独把素材挪到别的盘，可以在软件里「设置 → 高级 → 素材存放位置」改。"
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "立刻打开燧镜"
!define MUI_FINISHPAGE_RUN_FUNCTION "LaunchApp"
!define MUI_FINISHPAGE_SHOWREADME
!define MUI_FINISHPAGE_SHOWREADME_TEXT "看一下使用说明"
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION "OpenReadme"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

Var UPDATING

Function LaunchApp
  ExecShell "open" "$INSTDIR\${APP_EXE}"
FunctionEnd

Function OpenReadme
  ExecShell "open" "$INSTDIR\使用说明.txt"
FunctionEnd

; 把正在跑的东西全部关掉，否则文件被占用会装失败。
; 内置模组（手机音频接收、qBittorrent、口琴曲谱）都会占着 bundled 里的文件，
; 光杀主程序不够 —— 这个坑已经踩过一次。
Function KillAll
  ; 注意：这里刻意不用 /T。软件里点「检查更新」拉起安装器时，
  ; 安装器是 燧镜.exe 的子进程，/T 会把安装器自己一起杀掉。
  ; 内置模组各有各的进程名，单独杀就够了。
  nsExec::ExecToStack 'cmd.exe /c taskkill /F /IM ${APP_EXE}'
  Pop $0
  Pop $1
  nsExec::ExecToStack 'cmd.exe /c taskkill /F /IM AudioPlaybackConnector64.exe'
  Pop $0
  Pop $1
  nsExec::ExecToStack 'cmd.exe /c taskkill /F /IM qbittorrent.exe'
  Pop $0
  Pop $1
  nsExec::ExecToStack 'cmd.exe /c taskkill /F /IM "口琴可视化曲谱.exe"'
  Pop $0
  Pop $1
  ; 投屏模组拉起的 adb / scrcpy 会一直锁着 bundled\scrcpy\AdbWinApi.dll，
  ; 不关掉的话装到一半会弹「无法打开要写入的文件」。
  nsExec::ExecToStack 'cmd.exe /c taskkill /F /IM adb.exe'
  Pop $0
  Pop $1
  nsExec::ExecToStack 'cmd.exe /c taskkill /F /IM scrcpy.exe'
  Pop $0
  Pop $1
  ; 等文件句柄真正释放，否则马上覆盖 exe 会报"无法打开要写入的文件"
  Sleep 1200
FunctionEnd

Function .onInit
  ; /UPDATING = 软件自己拉起的一次升级：装完要把新版本重新打开
  ${GetParameters} $R0
  ${GetOptions} $R0 "/UPDATING" $R1
  StrCpy $UPDATING $R1

  Call KillAll
FunctionEnd

Section "主程序" SecMain
  SetShellVarContext current
  SetOutPath "$INSTDIR"

  ; ---- 装前把用户自己的东西挪到 $TEMP，装完再放回来 ----
  ; 配置
  ${If} ${FileExists} "$INSTDIR\config.json"
    ; CopyFiles 第二个参数必须是已存在的目录，给文件名会静默失败
    CreateDirectory "$TEMP\燧镜_keep"
    CopyFiles /SILENT "$INSTDIR\config.json" "$TEMP\燧镜_keep"
  ${Else}
    ; 这次装到了别的目录（或者换了安装位置）：旧目录里那份配置也得带上，
    ; 不然用户自己加的模组、热键、皮肤全归零，等于白升级。
    ReadRegStr $R2 HKCU "Software\燧镜" "InstallDir"
    ${If} $R2 != ""
      ${If} ${FileExists} "$R2\config.json"
        CreateDirectory "$TEMP\燧镜_keep"
        CopyFiles /SILENT "$R2\config.json" "$TEMP\燧镜_keep"
      ${EndIf}
    ${EndIf}
  ${EndIf}

  ; qBittorrent 的下载设置和种子列表（内置模组，被覆盖了用户会莫名其妙）
  ${If} ${FileExists} "$INSTDIR\bundled\qbittorrent\profile\*.*"
    nsExec::ExecToStack 'cmd.exe /c if exist "$TEMP\燧镜_qb.bak" rmdir /s /q "$TEMP\燧镜_qb.bak"'
    Pop $0
    Pop $1
    nsExec::ExecToStack 'cmd.exe /c xcopy /E /I /Y /Q "$INSTDIR\bundled\qbittorrent\profile" "$TEMP\燧镜_qb.bak"'
    Pop $0
    Pop $1
  ${EndIf}

  ; 口琴曲谱里用户自己加的歌
  ${If} ${FileExists} "$INSTDIR\bundled\口琴可视化曲谱\songs\*.*"
    nsExec::ExecToStack 'cmd.exe /c if exist "$TEMP\燧镜_songs.bak" rmdir /s /q "$TEMP\燧镜_songs.bak"'
    Pop $0
    Pop $1
    nsExec::ExecToStack 'cmd.exe /c xcopy /E /I /Y /Q "$INSTDIR\bundled\口琴可视化曲谱\songs" "$TEMP\燧镜_songs.bak"'
    Pop $0
    Pop $1
  ${EndIf}

  ; ---- 铺文件 ----
  File /r "${SRC_DIR}\*.*"

  ; ---- 把用户的东西放回来 ----
  ${If} ${FileExists} "$TEMP\燧镜_keep\config.json"
    CopyFiles /SILENT "$TEMP\燧镜_keep\config.json" "$INSTDIR"
    Delete "$TEMP\燧镜_keep\config.json"
    RMDir "$TEMP\燧镜_keep"
  ${EndIf}

  ${If} ${FileExists} "$TEMP\燧镜_qb.bak\*.*"
    nsExec::ExecToStack 'cmd.exe /c xcopy /E /I /Y /Q "$TEMP\燧镜_qb.bak" "$INSTDIR\bundled\qbittorrent\profile"'
    Pop $0
    Pop $1
    nsExec::ExecToStack 'cmd.exe /c rmdir /s /q "$TEMP\燧镜_qb.bak"'
    Pop $0
    Pop $1
  ${EndIf}

  ${If} ${FileExists} "$TEMP\燧镜_songs.bak\*.*"
    nsExec::ExecToStack 'cmd.exe /c xcopy /E /I /Y /Q "$TEMP\燧镜_songs.bak" "$INSTDIR\bundled\口琴可视化曲谱\songs"'
    Pop $0
    Pop $1
    nsExec::ExecToStack 'cmd.exe /c rmdir /s /q "$TEMP\燧镜_songs.bak"'
    Pop $0
    Pop $1
  ${EndIf}

  ; 快捷方式
  CreateShortCut "$DESKTOP\燧镜.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
  CreateDirectory "$SMPROGRAMS\燧镜"
  CreateShortCut "$SMPROGRAMS\燧镜\燧镜.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
  CreateShortCut "$SMPROGRAMS\燧镜\卸载 燧镜.lnk" "$INSTDIR\uninst.exe"

  ; 卸载信息（设置 → 应用 里能看到）
  WriteRegStr HKCU "Software\燧镜" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${REG_UNINST}" "DisplayName" "燧镜"
  WriteRegStr HKCU "${REG_UNINST}" "DisplayVersion" "${APP_VER}"
  WriteRegStr HKCU "${REG_UNINST}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKCU "${REG_UNINST}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
  WriteRegStr HKCU "${REG_UNINST}" "UninstallString" '"$INSTDIR\uninst.exe"'
  WriteRegStr HKCU "${REG_UNINST}" "QuietUninstallString" '"$INSTDIR\uninst.exe" /S'
  WriteRegStr HKCU "${REG_UNINST}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "${REG_UNINST}" "NoModify" 1
  WriteRegDWORD HKCU "${REG_UNINST}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${REG_UNINST}" "EstimatedSize" "$0"

  WriteUninstaller "$INSTDIR\uninst.exe"

  ; ---- 升级模式：装完自己把新版本打开 ----
  ; 静默安装不会走完成页，所以这里自己拉一次
  ${If} $UPDATING != ""
    ExecShell "open" "$INSTDIR\${APP_EXE}"
  ${EndIf}
SectionEnd

Section "Uninstall"
  SetShellVarContext current

  nsExec::ExecToStack 'cmd.exe /c taskkill /F /IM ${APP_EXE}'
  Pop $0
  Pop $1
  nsExec::ExecToStack 'cmd.exe /c taskkill /F /IM AudioPlaybackConnector64.exe'
  Pop $0
  Pop $1
  nsExec::ExecToStack 'cmd.exe /c taskkill /F /IM qbittorrent.exe'
  Pop $0
  Pop $1
  nsExec::ExecToStack 'cmd.exe /c taskkill /F /IM "口琴可视化曲谱.exe"'
  Pop $0
  Pop $1
  ; 投屏模组拉起的 adb / scrcpy 会一直锁着 bundled\scrcpy\AdbWinApi.dll，
  ; 不关掉的话装到一半会弹「无法打开要写入的文件」。
  nsExec::ExecToStack 'cmd.exe /c taskkill /F /IM adb.exe'
  Pop $0
  Pop $1
  nsExec::ExecToStack 'cmd.exe /c taskkill /F /IM scrcpy.exe'
  Pop $0
  Pop $1
  Sleep 800

  Delete "$DESKTOP\燧镜.lnk"
  Delete "$SMPROGRAMS\燧镜\燧镜.lnk"
  Delete "$SMPROGRAMS\燧镜\卸载 燧镜.lnk"
  RMDir "$SMPROGRAMS\燧镜"

  ; 素材和设置要不要一起删
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "要把「素材」文件夹（截图、录像）和设置一起删掉吗？$\r$\n$\r$\n选「否」只删程序，素材和配置留在 $INSTDIR，以后重装还能接着用。" \
    /SD IDNO IDYES del_all

  ; 只删程序
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR\bundled"
  Delete "$INSTDIR\${APP_EXE}"
  Delete "$INSTDIR\使用说明.txt"
  Delete "$INSTDIR\恢复分辨率.bat"
  Delete "$INSTDIR\燧镜手机版_*.apk"
  Delete "$INSTDIR\uninst.exe"
  RMDir "$INSTDIR"
  Goto done

del_all:
  RMDir /r "$INSTDIR"

done:
  DeleteRegKey HKCU "${REG_UNINST}"
  DeleteRegKey HKCU "Software\燧镜"
SectionEnd

BrandingText "燧镜 · FLINT MIRROR"
