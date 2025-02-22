# coding: utf-8
import re, os, time, sys, asyncio, webbrowser
import wx, requests
import xml.dom.minidom
from concurrent.futures import ThreadPoolExecutor,as_completed
from pubsub import pub

from SongSearchFrame import SongSearchFrame
from RoomSelectFrame import RoomSelectFrame
from ColorFrame import ColorFrame
from GeneralConfigFrame import GeneralConfigFrame
from RecordFrame import RecordFrame
from ShieldConfigFrame import ShieldConfigFrame
from CustomTextFrame import CustomTextFrame
from BiliLiveAntiShield import BiliLiveAntiShield
from PlayerFrame import PlayerFrame
from chaser.live_chaser import RoomPlayerChaser
from API import *
from constant import *
from util import *

LD_VERSION = "v1.4.3"

class LyricDanmu(wx.Frame):
    def __init__(self, parent):
        """B站直播同传/歌词弹幕发送工具"""
        # 获取操作系统信息
        self.platform="win" if sys.platform=="win32" else "mac"
        # 读取文件配置
        self.DefaultConfig()
        self.CheckFile()
        if not self.ReadFile(): return
        if self.no_proxy: os.environ["NO_PROXY"]="*"
        # 消息订阅
        pub.subscribe(self.UpdateRecord,"record")
        pub.subscribe(self.RefreshLyric,"lyric")
        pub.subscribe(setWxUIAttr,"ui_change")
        pub.subscribe(self.DealWithSpam,"spam")
        # API
        self.blApi = BiliLiveAPI(self.cookies,self.timeout_s)
        self.wyApi = NetEaseMusicAPI()
        self.qqApi = QQMusicAPI()
        self.jdApi = JsdelivrAPI()
        # 界面参数
        self.show_config = not self.init_show_lyric
        self.show_lyric = self.init_show_lyric
        self.show_import = False
        self.show_pin = True
        self.show_msg_dlg = False
        self.show_simple = False
        # B站配置参数
        self.cur_acc = 0
        self.roomid = None
        self.room_name = None
        self.colors={}
        self.modes={}
        self.cur_color=0
        self.cur_mode=0
        # 歌词参数
        self.init_lock = True
        self.cur_song_name=""
        self.last_song_name=""
        self.has_trans=False
        self.has_timeline=False
        self.auto_sending = False
        self.auto_pausing = False
        self.lyric_raw=""
        self.lyric_raw_tl=""
        self.timelines=[]
        self.llist=[]
        self.olist=[]
        self.lyc_mod = 1
        self.lid=0
        self.oid=0
        self.lmax=0
        self.omax=0
        self.cur_t=0
        self.pause_t=0
        self.timeline_base=0
        # 其他参数
        self.tmp_clipboard=""
        self.recent_danmu = [None,None]
        self.danmu_queue = []
        self.recent_history = []
        self.tmp_history = []
        self.running = True
        self.shield_changed = False
        self.history_state = False
        self.history_idx = 0
        self.colabor_mode = int(self.init_two_prefix)
        self.pre_idx = 0
        self.transparent = 255
        self.danmu_seq=1
        # 追帧服务
        self.live_chasing = False
        self.playerChaser=RoomPlayerChaser("1")
        # 线程池与事件循环
        self.pool = ThreadPoolExecutor(max_workers=8+len(self.admin_rooms))
        self.loop = asyncio.new_event_loop()
        # 显示界面与启动线程
        self.ShowFrame(parent)
        if self.need_update_global_shields:
            self.pool.submit(self.ThreadOfUpdateGlobalShields)
        self.pool.submit(self.ThreadOfSend)

    def DefaultConfig(self):
        self.rooms={}
        self.wy_marks = {}
        self.qq_marks = {}
        self.locals = {}
        self.custom_shields = {}
        self.room_shields = {}
        self.custom_texts = []
        self.danmu_log_dir = {}
        self.translate_records = {}
        self.translate_stat = []
        self.admin_rooms = []
        self.auto_shield_ad = False
        self.auto_mute_ad = False
        self.max_len = 30
        self.prefix = "【♪"
        self.suffix = "】"
        self.prefixs = ["【♪","【♬","【❀","【❄️","【★"]
        self.suffixs = ["","】"]
        self.enable_new_send_type=True
        self.send_interval_ms = 750
        self.timeout_s = 5
        self.default_src = "wy"
        self.search_num = 18
        self.page_limit = 6
        self.lyric_offset = 0
        self.enable_lyric_merge = True
        self.lyric_merge_threshold_s = 5.0
        self.add_song_name = False
        self.init_show_lyric = True
        self.init_show_record = False
        self.no_proxy = True
        self.account_names=["",""]
        self.cookies=["",""]
        self.need_update_global_shields = True
        self.tl_stat_break_min=10
        self.tl_stat_min_count=20
        self.tl_stat_min_word_num=200
        self.show_stat_on_close=False
        self.anti_shield = BiliLiveAntiShield({},[])
        self.init_two_prefix=False
        self.enable_rich_record=False
        self.record_fontsize=9 if self.platform=="win" else 13

    def ShowFrame(self, parent):
        # 窗体
        wx.Frame.__init__(self, parent, title="LyricDanmu %s - %s"%(LD_VERSION,self.account_names[0]),
            style=wx.DEFAULT_FRAME_STYLE ^ (wx.RESIZE_BORDER | wx.MAXIMIZE_BOX) | wx.STAY_ON_TOP)
        self.Bind(wx.EVT_CLOSE, self.OnClose)
        self.Bind(wx.EVT_MOVE, self.OnMove)
        self.Bind(wx.EVT_CHILD_FOCUS,self.OnFocus)
        self.songSearchFrame = None
        self.colorFrame = None
        self.generalConfigFrame = None
        self.customTextFrame = None
        self.playerFrame = None
        self.shieldConfigFrame = ShieldConfigFrame(self)
        self.roomSelectFrame = RoomSelectFrame(self)
        self.recordFrame = RecordFrame(self)
        if self.init_show_record:
            pos_x,pos_y=self.Position[0]+self.Size[0]+30,self.Position[1]+30
            self.recordFrame.SetPosition((pos_x,pos_y))
            self.recordFrame.Show()
        self.p0 = wx.Panel(self, -1, size=(450, 50), pos=(0, 0))
        self.p1 = wx.Panel(self, -1, size=(450, 360), pos=(0, 0))
        self.p2 = wx.Panel(self, -1, size=(450, 360), pos=(0, 0))
        self.p3 = wx.Panel(self, -1, size=(450, 85), pos=(0, 0))
        self.p4 = wx.Panel(self.p3, -1, size=(345,100), pos=(105,2))
        """ P0 弹幕输入面板 """
        # 前缀选择
        self.cbbComPre = wx.ComboBox(self.p0, -1, pos=(15, 13), size=(60, -1), choices=["【", "", "", "", ""], style=wx.CB_DROPDOWN, value="")
        self.cbbComPre.Bind(wx.EVT_TEXT, self.CountText)
        self.cbbComPre.Bind(wx.EVT_COMBOBOX, self.CountText)
        # 弹幕输入框
        self.tcComment = wx.TextCtrl(self.p0, -1, "", pos=(82, 10), size=(255, 30), style=wx.TE_PROCESS_ENTER|wx.TE_PROCESS_TAB)
        self.tcComment.Bind(wx.EVT_TEXT_ENTER, self.SendComment)
        self.tcComment.Bind(wx.EVT_KEY_DOWN, self.OnKeyDown)
        self.tcComment.Bind(wx.EVT_TEXT, self.CountText)
        self.tcComment.Bind(wx.EVT_TEXT, self.FetchFromTmpClipboard)
        self.tcComment.Bind(wx.EVT_TEXT_PASTE, self.OnPasteComment)
        # 弹幕发送按钮
        self.btnComment = wx.Button(self.p0, -1, "00 ↩", pos=(345, 9), size=(47, 32))
        self.btnComment.Bind(wx.EVT_BUTTON, self.SendComment)
        # 同传配置拓展按钮
        self.btnExt = wx.Button(self.p0, -1, "▼", pos=(400, 9), size=(32, 32))
        self.btnExt.Bind(wx.EVT_BUTTON, self.ToggleConfigUI)
        """ P1 歌词主面板 """
        # 直播间选择
        self.btnRoom2 = wx.Button(self.p1, -1, "选择直播间", pos=(15, 9), size=(87, 32))
        self.btnRoom2.Bind(wx.EVT_BUTTON,self.ShowRoomSelectFrame)
        # 歌词搜索
        if self.default_src=="wy":
            self.tcSearch = wx.TextCtrl(self.p1, -1, "", pos=(111, 10), size=(196, 30), style=wx.TE_PROCESS_ENTER, name="wy")
            self.btnSearch = wx.Button(self.p1, -1, "网易云 ↩", pos=(315, 9), size=(62, 32), name="wy")
            self.btnSearch2 = wx.Button(self.p1, -1, "QQ", pos=(382, 9), size=(49, 32), name="qq")
        else:
            self.tcSearch = wx.TextCtrl(self.p1, -1, "", pos=(111, 10), size=(196, 30), style=wx.TE_PROCESS_ENTER, name="qq")
            self.btnSearch = wx.Button(self.p1, -1, "QQ ↩", pos=(315, 9), size=(62, 32), name="qq")
            self.btnSearch2 = wx.Button(self.p1, -1, "网易云", pos=(382, 9), size=(49, 32), name="wy")
        self.tcSearch.Bind(wx.EVT_TEXT_ENTER, self.SearchLyric)
        self.tcSearch.Bind(wx.EVT_TEXT, self.FetchFromTmpClipboard)
        self.tcSearch.Bind(wx.EVT_TEXT_PASTE, self.OnPasteSearch)
        self.btnSearch.Bind(wx.EVT_BUTTON, self.SearchLyric)
        self.btnSearch2.Bind(wx.EVT_BUTTON, self.SearchLyric)
        # 歌词静态文本
        self.lblLyrics = []
        self.lblTimelines = []
        for i in range(11):
            timeline_content=wx.StaticText(self.p1, -1, "", pos=(0, 140 + 20 * i), size=(35, 19), style=wx.ALIGN_CENTER | wx.ST_NO_AUTORESIZE)
            lyric_content = wx.StaticText(self.p1, -1, "", pos=(35, 140 + 20 * i), size=(375, 19), style=wx.ALIGN_CENTER | wx.ST_NO_AUTORESIZE)
            timeline_content.SetForegroundColour("gray")
            self.lblLyrics.append(lyric_content)
            self.lblTimelines.append(timeline_content)
        self.lblLyrics[4].SetForegroundColour("blue")
        self.lblTimelines[4].SetForegroundColour("blue")
        # 歌词弹幕配置
        txtLycMod = wx.StaticText(self.p1, -1, "模式", pos=(15, 54))
        txtLycPre = wx.StaticText(self.p1, -1, "前缀", pos=(15, 84))
        txtLycSuf = wx.StaticText(self.p1, -1, "后缀", pos=(15, 114))
        self.cbbLycMod = wx.ComboBox(self.p1, -1, pos=(45, 50), size=(57, -1), choices=["原版", "中文", "双语"], style=wx.CB_READONLY, value="中文")
        self.cbbLycPre = wx.ComboBox(self.p1, -1, pos=(45, 80), size=(57, -1), choices=self.prefixs, style=wx.CB_DROPDOWN, value=self.prefix)
        self.cbbLycSuf = wx.ComboBox(self.p1, -1, pos=(45, 110), size=(57, -1), choices=self.suffixs, style=wx.CB_DROPDOWN, value=self.suffix)
        self.cbbLycMod.Bind(wx.EVT_COMBOBOX, self.SetLycMod)
        # 歌词调整/发送按钮
        self.btnLycImpIn = wx.Button(self.p1, -1, "导入歌词", pos=(110, 49), size=(62, 42))
        self.btnCopyAll = wx.Button(self.p1, -1, "复制全文", pos=(110, 94), size=(62, 42))
        self.btnClearQueue = wx.Button(self.p1, -1, "清空队列", pos=(178, 49), size=(62, 42))
        self.btnCopyLine = wx.Button(self.p1, -1, "复制此句", pos=(178, 94), size=(62, 42))
        self.btnPrev = wx.Button(self.p1, -1, "▲", pos=(246, 49), size=(62, 42))
        self.btnNext = wx.Button(self.p1, -1, "▼", pos=(246, 94), size=(62, 42))
        self.btnSend = wx.Button(self.p1, -1, "手动发送", pos=(315, 49), size=(62, 42)) #116
        self.btnCustomText = wx.Button(self.p1, -1, "预设", pos=(382, 49), size=(49, 42))
        self.btnAutoSend = wx.Button(self.p1, -1, "自动 ▶", pos=(315, 94), size=(62, 42))
        self.btnStopAuto = wx.Button(self.p1, -1, "停止 □", pos=(382, 94), size=(49, 42))
        self.btnLycImpIn.Bind(wx.EVT_BUTTON, self.ToggleImportUI)
        self.btnClearQueue.Bind(wx.EVT_BUTTON, self.ClearQueue)
        self.btnCopyLine.Bind(wx.EVT_BUTTON, self.CopyLyricLine)
        self.btnCopyAll.Bind(wx.EVT_BUTTON, self.CopyLyricAll)
        self.btnPrev.Bind(wx.EVT_BUTTON, self.PrevLyric)
        self.btnNext.Bind(wx.EVT_BUTTON, self.NextLyric)
        self.btnSend.Bind(wx.EVT_BUTTON, self.OnSendLrcBtn)
        self.btnCustomText.Bind(wx.EVT_BUTTON, self.ShowCustomTextFrame)
        self.btnAutoSend.Bind(wx.EVT_BUTTON, self.OnAutoSendLrcBtn)
        self.btnStopAuto.Bind(wx.EVT_BUTTON, self.OnStopBtn)
        # 歌词进度滑块
        self.sldLrc = wx.Slider(self.p1, -1, 0, 0, 10, pos=(415, 155), size=(30, 195), style=wx.SL_VERTICAL)
        self.sldLrc.Bind(wx.EVT_SLIDER, self.OnLyricLineChange)
        self.lblCurLine = wx.StaticText(self.p1, -1, "", pos=(420, 137))
        self.lblMaxLine = wx.StaticText(self.p1, -1, "", pos=(420, 347))
        self.sldLrc.Show(False)
        """ P2 歌词导入面板 """
        # 歌词导入部分
        self.btnLycImpOut = wx.Button(self.p2, -1, "◀   返  回    ", pos=(15, 9), size=(96, 32))
        self.cbbImport = wx.ComboBox(self.p2, -1, pos=(271, 13), size=(60, -1), choices=["单语", "双语"], style=wx.CB_READONLY, value="单语")
        self.btnImport = wx.Button(self.p2, -1, "导入歌词", pos=(345, 9), size=(87, 32))
        self.btnLycImpOut.Bind(wx.EVT_BUTTON, self.ToggleImportUI)
        self.btnImport.Bind(wx.EVT_BUTTON, self.ImportLyric)
        self.cbbImport.Bind(wx.EVT_COMBOBOX, self.SynImpLycMod)
        # 歌词保存部分
        self.tcImport = wx.TextCtrl(self.p2, -1, "", pos=(15, 49), size=(416, 180), style=wx.TE_MULTILINE)
        lblSongName = wx.StaticText(self.p2, -1, "歌名", pos=(15, 244))
        self.tcSongName = wx.TextCtrl(self.p2, -1, "", pos=(45, 240), size=(200, 27))
        lblArtists = wx.StaticText(self.p2, -1, "作者", pos=(263, 244))
        self.tcArtists = wx.TextCtrl(self.p2, -1, "", pos=(291, 240), size=(140, 27))
        lblTagDesc = wx.StaticText(self.p2, -1, "添加其他标签便于检索，使用分号或换行进行分割。", pos=(15, 272), size=(322,-1))
        self.tcTags = wx.TextCtrl(self.p2, -1, "", pos=(15, 292), size=(322, 65), style=wx.TE_MULTILINE)
        self.cbbImport2 = wx.ComboBox(self.p2, -1, pos=(346, 292), size=(85, -1), choices=["单语", "双语"], style=wx.CB_READONLY, value="单语")
        self.btnSaveToLocal = wx.Button(self.p2, -1, "保存至本地", pos=(345, 326), size=(87, 32))
        self.cbbImport2.Bind(wx.EVT_COMBOBOX, self.SynImpLycMod)
        self.btnSaveToLocal.Bind(wx.EVT_BUTTON,self.SaveToLocal)
        """ P3 配置主面板 """
        # 直播间选择
        self.btnRoom1 = wx.Button(self.p3, -1, "选择直播间", pos=(15, 3), size=(87, 32))
        self.btnRoom1.Bind(wx.EVT_BUTTON, self.ShowRoomSelectFrame)
        # 弹幕颜色/位置选择
        self.btnDmCfg1 = wx.Button(self.p3, -1, "██", pos=(15, 40), size=(43, 32))
        self.btnDmCfg2 = wx.Button(self.p3, -1, "⋘", pos=(59, 40), size=(43, 32))
        if self.platform=="win":
            self.btnDmCfg1.SetBackgroundColour(wx.Colour(250,250,250))
            setFont(self.btnDmCfg2,13,name="微软雅黑")
        self.btnDmCfg1.Disable()
        self.btnDmCfg2.Disable()
        self.btnDmCfg1.Bind(wx.EVT_BUTTON, self.ShowColorFrame)
        self.btnDmCfg2.Bind(wx.EVT_BUTTON, self.ChangeDanmuPosition)
        # 同传前缀与模式设置
        self.btnColaborCfg = wx.Button(self.p3, -1, "单人模式+" if self.init_two_prefix else "单人模式", pos=(125, 3), size=(87, 32))
        self.btnColaborCfg.Bind(wx.EVT_BUTTON,self.ShowColaborPart)
        # 常规设置按钮
        self.btnGeneralCfg = wx.Button(self.p3, -1, "应用设置", pos=(235, 3), size=(87, 32))
        self.btnGeneralCfg.Bind(wx.EVT_BUTTON,self.ShowGeneralConfigFrame)
        # 弹幕记录按钮
        self.btnShowRecord = wx.Button(self.p3, -1, "弹幕记录", pos=(125, 40), size=(87, 32))
        self.btnShowRecord.Bind(wx.EVT_BUTTON,self.ShowRecordFrame)
        # 屏蔽词管理按钮
        self.btnShieldCfg=wx.Button(self.p3,-1,"屏蔽词管理",pos=(235, 40), size=(87, 32))
        self.btnShieldCfg.Bind(wx.EVT_BUTTON,self.ShowShieldConfigFrame)
        # 歌词面板展开按钮
        self.btnExtLrc = wx.Button(self.p3, -1, "收起歌词" if self.init_show_lyric else "歌词面板", pos=(345, 3), size=(87, 32))
        self.btnExtLrc.Bind(wx.EVT_BUTTON, self.ToggleLyricUI)
        # 追帧按钮
        self.btnChaser = wx.Button(self.p3, -1, "追帧", pos=(345,40), size=(42,32))
        self.btnChaser.Bind(wx.EVT_BUTTON, self.ShowPlayer)
        # 置顶按钮
        self.btnTop = wx.Button(self.p3, -1, "置顶", pos=(390, 40), size=(42, 32))
        self.btnTop.Bind(wx.EVT_BUTTON, self.TogglePinUI)
        """ P4 多人联动面板 """
        wx.StaticText(self.p4, -1, "1", pos=(15, 10))
        wx.StaticText(self.p4, -1, "2", pos=(90, 10))
        wx.StaticText(self.p4, -1, "3", pos=(165, 10))
        wx.StaticText(self.p4, -1, "4", pos=(15, 42))
        wx.StaticText(self.p4, -1, "5", pos=(90, 42))
        self.tcPre1 = wx.TextCtrl(self.p4, -1, "【", pos=(25, 6), size=(55, 25), name="0")
        self.tcPre2 = wx.TextCtrl(self.p4, -1, "", pos=(100, 6), size=(55, 25), name="1")
        self.tcPre3 = wx.TextCtrl(self.p4, -1, "", pos=(175, 6), size=(55, 25), name="2")
        self.tcPre4 = wx.TextCtrl(self.p4, -1, "", pos=(25, 38), size=(55, 25), name="3")
        self.tcPre5 = wx.TextCtrl(self.p4, -1, "", pos=(100, 38), size=(55, 25), name="4")
        for x in (self.tcPre1, self.tcPre2, self.tcPre3, self.tcPre4, self.tcPre5):
            x.Bind(wx.EVT_TEXT,self.OnClbPreChange)
        self.ckbTabMod = wx.CheckBox(self.p4,-1,"Tab切换",pos=(162,43))
        self.ckbTabMod.SetForegroundColour("gray")
        self.ckbTabMod.SetValue(True)
        wx.StaticText(self.p4,-1,"⍰",pos=(230,40)).SetToolTip(
            "联动模式下使用Tab键切换前缀，切换范围取决于联动人数\n" +
            "也可以直接使用Alt+数字键1~5来切换到指定的前缀\n")
        self.cbbClbMod = wx.ComboBox(self.p4, pos=(250, 6), size=(72, -1), style=wx.CB_READONLY, choices=["不切换", "双前缀", "三前缀", "四前缀", "五前缀"])
        self.cbbClbMod.SetSelection(self.colabor_mode)
        self.cbbClbMod.Bind(wx.EVT_COMBOBOX, self.SetColaborMode)
        self.btnExitClbCfg = wx.Button(self.p4, -1, "◀  返  回  ", pos=(250, 37), size=(72, 27))
        self.btnExitClbCfg.Bind(wx.EVT_BUTTON, self.ExitColaborPart)
        # HotKey
        self.hkIncTp=wx.NewIdRef()
        self.hkDecTp=wx.NewIdRef()
        self.hkSimple=wx.NewIdRef()
        self.RegisterHotKey(self.hkIncTp,wx.MOD_ALT,wx.WXK_UP)
        self.RegisterHotKey(self.hkDecTp,wx.MOD_ALT,wx.WXK_DOWN)
        self.RegisterHotKey(self.hkSimple,wx.MOD_ALT,wx.WXK_RIGHT)
        self.Bind(wx.EVT_HOTKEY,self.IncreaseTransparent,self.hkIncTp)
        self.Bind(wx.EVT_HOTKEY,self.DecreaseTransparent,self.hkDecTp)
        self.Bind(wx.EVT_HOTKEY,self.ToggleSimpleMode,self.hkSimple)
        # MAC系统界面调整
        if self.platform=="mac":
            setFont(self,13)
            for obj in self.p1.Children:
                setFont(obj,10)
            for obj in [txtLycMod,txtLycPre,txtLycSuf,self.cbbLycMod,
                        self.cbbLycPre,self.cbbLycSuf,self.btnRoom2,self.tcSearch]:
                setFont(obj,13)
            for i in range(11):
                setFont(self.lblTimelines[i],12)
                setFont(self.lblLyrics[i],13)
        # 焦点与显示
        self.tcSearch.SetFocus() if self.init_show_lyric else self.tcComment.SetFocus()
        self.p0.Show(True)
        self.p1.Show(True)
        self.p2.Show(False)
        self.p3.Show(True)
        self.p4.Show(False)
        self.ResizeUI()
        self.Show(True)
        if self.platform=="mac":
            self.ShowRoomSelectFrame(None)

    def ShowCustomTextFrame(self,event):
        if self.customTextFrame:
            self.customTextFrame.Raise()
        else:
            self.customTextFrame=CustomTextFrame(self)

    def ShowRoomSelectFrame(self,event):
        if self.roomSelectFrame:
            self.roomSelectFrame.Raise()
        else:
            self.roomSelectFrame=RoomSelectFrame(self)

    def ShowShieldConfigFrame(self,event):
        self.shieldConfigFrame.Show(True)
        self.shieldConfigFrame.Raise()

    def ShowGeneralConfigFrame(self,event):
        if self.generalConfigFrame:
            self.generalConfigFrame.Raise()
        else:
            self.generalConfigFrame=GeneralConfigFrame(self)

    def ShowRecordFrame(self,event):
        self.recordFrame.Show()
        self.recordFrame.Restore()
        self.recordFrame.Raise()

    def ShowColorFrame(self,event):
        if self.colorFrame is not None:
            self.colorFrame.Destroy()
        self.colorFrame=ColorFrame(self)

    def ShowColaborPart(self,event):
        self.p4.Show(True)
        self.btnColaborCfg.Show(False)
        self.btnGeneralCfg.Show(False)
        self.btnShowRecord.Show(False)
        self.btnShieldCfg.Show(False)
        self.btnExtLrc.Show(False)
        self.btnTop.Show(False)
    
    def ShowPlayer(self,event):
        if not self.live_chasing:
            if self.roomid is None:
                return showInfoDialog("未指定直播间", "提示")
            self.pool.submit(self.RunRoomPlayerChaser,self.roomid,self.loop)
            self.live_chasing=True
            self.btnChaser.SetForegroundColour("MEDIUM BLUE")
        dlg = wx.MessageDialog(None, "[是] 浏览器打开(推荐)　　　[否] 工具自带窗体打开", "选择追帧显示方式", wx.YES_NO|wx.YES_DEFAULT)
        res = dlg.ShowModal()
        if res==wx.ID_YES:
            webbrowser.open("http://127.0.0.1:8080/player.html")
        elif res==wx.ID_NO:
            if self.playerFrame: self.playerFrame.Raise()
            else:   self.playerFrame=PlayerFrame(self)
        dlg.Destroy()
    
    def ExitColaborPart(self,event):
        mode_names=["单人模式","双人联动","三人联动","四人联动","五人联动"]
        sp_mode=self.colabor_mode==1 and (isEmpty(self.tcPre1.GetValue()) or isEmpty(self.tcPre2.GetValue()))
        label="单人模式+" if sp_mode else mode_names[self.cbbClbMod.GetSelection()]
        self.btnColaborCfg.SetLabel(label)
        self.p4.Show(False)
        self.btnColaborCfg.Show(True)
        self.btnGeneralCfg.Show(True)
        self.btnShowRecord.Show(True)
        self.btnShieldCfg.Show(True)
        self.btnExtLrc.Show(True)
        self.btnTop.Show(True)

    def IncreaseTransparent(self,event):
        self.transparent=min(255,self.transparent+15)
        self.SetTransparent(self.transparent)
    
    def DecreaseTransparent(self,event):
        self.transparent=max(30,self.transparent-15)
        self.SetTransparent(self.transparent)
    
    def ToggleSimpleMode(self,event):
        self.show_simple=not self.show_simple
        self.ToggleWindowStyle(wx.CAPTION)
        px,py=self.GetPosition()
        if self.show_simple:
            self.cbbComPre.SetPosition((0, 0))
            self.tcComment.SetPosition((60, 0))
            self.p0.SetPosition((0,0))
            self.p1.Show(False)
            self.p2.Show(False)
            self.SetPosition((px+25,py+35+int(self.show_lyric)*self.p1.GetSize()[1]))
            self.SetSize(315,30)
            self.p0.SetBackgroundColour("white")
        else:
            self.cbbComPre.SetPosition((15, 13))
            self.tcComment.SetPosition((82, 10))
            self.SetPosition((px-25,py-35-int(self.show_lyric)*self.p1.GetSize()[1]))
            self.p0.SetBackgroundColour(self.p1.GetBackgroundColour())
            self.ResizeUI()
            self.tcComment.SetFocus()

    def TogglePinUI(self, event):
        self.show_pin = not self.show_pin
        self.ToggleWindowStyle(wx.STAY_ON_TOP)
        self.btnTop.SetForegroundColour("black" if self.show_pin else "gray")

    def ToggleLyricUI(self, event):
        self.show_lyric = not self.show_lyric
        self.btnExtLrc.SetLabel("收起歌词" if self.show_lyric else "歌词面板")
        if self.show_lyric: self.tcSearch.SetFocus()
        else: self.tcComment.SetFocus()
        self.ResizeUI()

    def ToggleConfigUI(self, event):
        self.tcComment.SetFocus()
        self.show_config = not self.show_config
        self.btnExt.SetLabel("▲" if self.show_config else "▼")
        self.ResizeUI()

    def ToggleImportUI(self, event):
        self.show_import=not self.show_import
        self.ResizeUI()

    def ResizeUI(self):
        w,h=self.p0.GetSize()
        h1=self.p1.GetSize()[1]
        h3=self.p3.GetSize()[1]
        if self.show_lyric:
            h+=h1
            self.p0.SetPosition((0,h1))
            if self.show_import:
                self.p2.Show(True)
                self.p1.Show(False)
            else:
                self.p1.Show(True)
                self.p2.Show(False)
        else:
            self.p0.SetPosition((0, 0))
            self.p1.Show(False)
            self.p2.Show(False)
        if self.show_config:
            self.p3.SetPosition((0, h))
            self.p3.Show(True)
            h+=h3
        else:
            self.p3.Show(False)
        self.SetSize((w, h+25))# 考虑标题栏高度


    def ThreadOfGetDanmuConfig(self):
        UIChange(self.btnRoom1,enabled=False)
        UIChange(self.btnRoom2,enabled=False)
        UIChange(self.btnDmCfg1,enabled=False)
        UIChange(self.btnDmCfg2,enabled=False)
        if self.GetCurrentDanmuConfig():
            self.GetUsableDanmuConfig()
            UIChange(self.btnDmCfg1,color=getRgbColor(self.cur_color),enabled=True)
            UIChange(self.btnDmCfg2,label=BILI_MODES[str(self.cur_mode)],enabled=True)
        else:
            self.roomid = None
            self.room_name = None
            self.GetRoomShields()
            UIChange(self.btnRoom1,label="选择直播间")
            UIChange(self.btnRoom2,label="选择直播间")
        UIChange(self.btnRoom1,enabled=True)
        UIChange(self.btnRoom2,enabled=True)

    def ThreadOfSetDanmuConfig(self,color,mode):
        try:
            data=self.blApi.set_danmu_config(self.roomid,color,mode,self.cur_acc)
            if data["code"]!=0:
                return showInfoDialog("设置失败，请重试", "保存弹幕配置出错")
            if color is not None:
                self.cur_color=int(color,16)
                UIChange(self.btnDmCfg1,color=getRgbColor(self.cur_color))
            else:
                self.cur_mode=mode
                UIChange(self.btnDmCfg2,label=BILI_MODES[mode])
        except requests.exceptions.ConnectionError:
            return showInfoDialog("网络异常，请重试", "保存弹幕配置出错")
        except requests.exceptions.ReadTimeout:
            return showInfoDialog("获取超时，请重试", "保存弹幕配置出错")
        except Exception:
            return showInfoDialog("解析错误，请重试", "保存弹幕配置出错")
        return True

    def ThreadOfSend(self):
        last_time = 0
        while self.running:
            try:
                wx.MilliSleep(FETCH_INTERVAL_MS)
                if len(self.danmu_queue) == 0:
                    continue
                danmu = self.danmu_queue.pop(0)
                interval_s = 0.001 * self.send_interval_ms + last_time - time.time()
                if interval_s > 0:
                    wx.MilliSleep(int(1000 * interval_s))
                if self.enable_new_send_type: #新版机制
                    task = [self.pool.submit(self.SendDanmu, danmu[0], danmu[1], danmu[2], danmu[3])]
                    for i in as_completed(task):    pass
                else: #旧版机制
                    self.pool.submit(self.SendDanmu, danmu[0], danmu[1], danmu[2], danmu[3])
                last_time = time.time()
                UIChange(self.btnClearQueue,label="清空 [%d]" % len(self.danmu_queue))  #
            except RuntimeError:    pass
            except Exception as e:
                return showInfoDialog("弹幕发送线程出错，请重启并将问题反馈给作者\n" + str(e), "发生错误")

    def ThreadOfAutoSend(self):
        self.cur_t=self.timelines[self.oid]
        next_t=self.timelines[self.oid+1]
        self.timeline_base=time.time()-self.cur_t
        while self.auto_sending and next_t>=0:
            if self.auto_pausing:
                wx.MilliSleep(48)
                continue
            if self.cur_t>= next_t:
                self.NextLyric(None)
                if self.has_trans and self.lyc_mod == 2 and self.llist[self.lid-1][2]!=self.llist[self.lid][2]:
                    self.SendLyric(3)
                self.SendLyric(4)
                next_t=self.timelines[self.oid+1]
            UIChange(self.btnSend,label=getTimeLineStr(self.cur_t))
            self.cur_t = time.time()-self.timeline_base
            wx.MilliSleep(48)
        self.OnStopBtn(None)

    def ThreadOfUpdateGlobalShields(self):
        if os.path.exists("tmp.tmp"):   return
        with open("tmp.tmp","w",encoding="utf-8") as f:  f.write("")
        try:
            UIChange(self.shieldConfigFrame.btnUpdateGlobal,label="获取更新中…")
        except Exception as e:
            print(type(e),e)
        try:
            code=""
            data=self.jdApi.get_latest_bili_live_shield_words(timeout=(6,10))
            so=re.search(r"# <DATA BEGIN>([\s\S]*?)# <DATA END>",data)
            code=so.group(1).replace("and not measure(x.group(3),4)","") #简化某条特殊规则
        except:
            UIChange(self.shieldConfigFrame.btnUpdateGlobal,label="无法获取更新")
        try:
            if code=="":    return
            # 写入内存
            scope = {"words":[],"rules":{}}
            exec(code,scope)
            self.anti_shield=BiliLiveAntiShield(scope["rules"],scope["words"])
            # 写入文件
            with open("shields_global.dat", "wb") as f:
                f.write(bytes(code,encoding="utf-8"))
                f.write(bytes("modified_time=%d"%int(time.time()),encoding="utf-8"))
                f.write(bytes("  # 最近一次更新时间：%s"%getTime(fmt="%m-%d %H:%M"),encoding="utf-8"))
            UIChange(self.shieldConfigFrame.btnUpdateGlobal,label="词库更新完毕")
        except:
            UIChange(self.shieldConfigFrame.btnUpdateGlobal,label="云端数据有误")
        finally:
            try:    os.remove("tmp.tmp")
            except: pass

    def ThreadOfShowMsgDlg(self,content,title):
        if self.show_msg_dlg:   return
        self.show_msg_dlg=True
        showInfoDialog(content,title)
        wx.MilliSleep(3000)
        self.show_msg_dlg=False
    
    def ThreadOfAdminMuteUser(self,roomid,uid,uname):
        try:
            msg="【封禁】房间号：%s，用户名：%s，UID：%s，操作结果："%(roomid,uname,uid)
            data=self.blApi.add_slient_user(roomid,uid)
            if data["code"]==0: msg+="成功"
            else: msg+=data["message"]
        except requests.exceptions.ConnectionError: msg+="网络异常"
        except requests.exceptions.ReadTimeout: msg+="请求超时"
        except Exception: msg+="解析错误"
        finally: self.LogSpam(msg)

    def ThreadOfAdminAddRoomShield(self,roomid,keyword):
        try:
            msg="【屏蔽】房间号：%s，关键词：%s，操作结果："%(roomid,keyword)
            data=self.blApi.add_shield_keyword(roomid,keyword)
            if data["code"]==0: msg+="成功"
            else: msg+=data["message"]
        except requests.exceptions.ConnectionError: msg+="网络异常"
        except requests.exceptions.ReadTimeout: msg+="请求超时"
        except Exception: msg+="解析错误"
        finally: self.LogSpam(msg)


    def OnAutoSendLrcBtn(self,event):
        if self.init_lock or not self.has_timeline:
            return
        if self.auto_sending:
            if self.auto_pausing:
                resume_t=time.time()
                self.timeline_base+=resume_t-self.pause_t
                self.auto_pausing=False
                self.btnAutoSend.SetLabel("暂停 ⏸")
            else:
                self.pause_t=time.time()
                self.auto_pausing=True
                self.btnAutoSend.SetLabel("继续 ▶")
            return
        if self.roomid is None:
            return showInfoDialog("未指定直播间", "提示")
        if not self.NextLyric(None):
            return
        if self.has_trans and self.lyc_mod == 2 and self.llist[self.lid-1][2]!=self.llist[self.lid][2]:
            self.SendLyric(3)
        self.SendLyric(4)
        self.sldLrc.Disable()
        self.btnPrev.SetLabel("推迟半秒△")
        self.btnNext.SetLabel("提早半秒▽")
        self.btnStopAuto.SetLabel("停止 ■")
        self.btnAutoSend.SetLabel("暂停 ⏸")
        self.auto_sending=True
        self.auto_pausing=False
        self.pool.submit(self.ThreadOfAutoSend)
        if self.cur_song_name!=self.last_song_name:
            self.last_song_name=self.cur_song_name
            self.LogSongName("%8s\t%s"%(self.roomid,self.cur_song_name))

    def OnStopBtn(self,event):
        if self.init_lock:
            return
        self.auto_sending=False
        self.auto_pausing=False
        self.btnPrev.SetLabel("▲")
        self.btnNext.SetLabel("▼")
        self.btnStopAuto.SetLabel("停止 □")
        self.btnSend.SetLabel("手动发送")
        self.btnAutoSend.SetLabel("自动 ▶")
        self.sldLrc.Enable()
 
    def OnClbPreChange(self,event):
        tcPre=event.GetEventObject()
        index=int(tcPre.GetName())
        pre1=tcPre.GetValue()
        pre2=pre1.lstrip()
        if pre1 != pre2:
            tcPre.SetValue(pre2)
            return
        pre2=re.sub(r"[ 　]{2,}$","　",pre2)
        if pre1 != pre2:
            tcPre.SetValue(pre2)
            tcPre.SetInsertionPointEnd()
            return
        self.cbbComPre.SetString(index, pre2)
        if index==self.pre_idx:
            self.cbbComPre.SetSelection(self.pre_idx)
        self.CountText(None)

    def SynImpLycMod(self,event):
        mode=event.GetEventObject().GetSelection()
        self.cbbImport.SetSelection(mode)
        self.cbbImport2.SetSelection(mode)

    def OnLyricLineChange(self, event):
        self.oid = self.sldLrc.GetValue()
        self.lblCurLine.SetLabel(str(self.oid))
        self.lid = self.olist[self.oid]
        if self.has_trans and self.lyc_mod > 0:
            self.lid += 1
        wx.CallAfter(pub.sendMessage,"lyric")

    def ImportLyric(self, event):
        lyric = self.tcImport.GetValue().strip()
        if lyric == "":
            return showInfoDialog("歌词不能为空", "歌词导入失败")
        if lyric.count("\n") <= 4 or len(lyric) <= 50:
            return showInfoDialog("歌词内容过短", "歌词导入失败")
        has_trans = self.cbbImport.GetSelection() == 1
        ldata={
            "src": "local",
            "has_trans": has_trans,
            "lyric": lyric,
            "name": "",
        }
        self.RecvLyric(ldata)

    def OnKeyDown(self, event):
        keycode = event.GetKeyCode()
        if keycode == 315: # ↑键
            if len(self.recent_history)==0: return
            if self.history_state:
                if self.history_idx+1<len(self.tmp_history):
                    self.history_idx+=1
                self.tcComment.SetValue(self.tmp_history[self.history_idx])
                self.tcComment.SetInsertionPointEnd()
            else:
                self.tmp_history=self.recent_history[:]
                self.history_idx=0
                self.tcComment.SetValue(self.tmp_history[0])
                self.tcComment.SetInsertionPointEnd()
                self.history_state=True
            return
        if keycode == 317: # ↓键
            if not self.history_state:  return
            self.history_idx-=1
            if self.history_idx>=0:
                self.tcComment.SetValue(self.tmp_history[self.history_idx])
                self.tcComment.SetInsertionPointEnd()
            else:
                self.tcComment.Clear()
                self.history_state=False
            return
        if keycode == 9:  # Tab键
            if self.colabor_mode == 0 or not self.ckbTabMod.GetValue():
                return
            if event.GetModifiers()==wx.MOD_SHIFT:
                self.pre_idx = self.pre_idx - 1 if self.pre_idx > 0 else self.colabor_mode
            else:
                self.pre_idx = self.pre_idx + 1 if self.pre_idx < self.colabor_mode else 0
            self.cbbComPre.SetSelection(self.pre_idx)
            self.CountText(None)
            return
        if event.GetModifiers()==wx.MOD_ALT:
            if 49 <= keycode and keycode <= 53:  # 12345
                self.pre_idx = keycode - 49
                self.cbbComPre.SetSelection(self.pre_idx)
            return
        event.Skip()

    def CountText(self, event):
        comment = self.cbbComPre.GetValue() + self.tcComment.GetValue()
        label = "%02d" % len(comment) + (" ↩" if len(comment) <= self.max_len*2.5 else " ×")
        self.btnComment.SetLabel(label)
        if event is not None:
            event.Skip()

    def SetLycMod(self, event):
        self.lyc_mod = self.cbbLycMod.GetSelection()
        if not self.init_lock:
            self.lid = self.olist[self.oid+self.lyric_offset]+int(self.has_trans and self.lyc_mod>0)
        self.RefreshLyric()

    def CopyLyricLine(self, event):
        if self.init_lock:  return
        wxCopy(self.lblLyrics[4].GetLabel())

    def CopyLyricAll(self, event):
        if self.init_lock:  return
        if self.has_timeline:
            dlg = wx.MessageDialog(None, "是否复制歌词时间轴？", "提示", wx.YES_NO|wx.NO_DEFAULT)
            wxCopy(self.lyric_raw_tl if dlg.ShowModal()==wx.ID_YES else self.lyric_raw)
            dlg.Destroy()
        else:
            wxCopy(self.lyric_raw)

    def ClearQueue(self,event):
        self.danmu_queue.clear()
        UIChange(self.btnClearQueue,label="清空 [0]")

    def PrevLyric(self, event):
        if self.init_lock:  return
        # 自动模式下，延缓进度
        if self.auto_sending and event is not None:
            self.timeline_base+=0.5
            self.cur_t-=0.5
            UIChange(self.btnSend,label=getTimeLineStr(self.cur_t))
            return
        # 手动模式下，上一句
        if self.oid <= 0:
            return False
        self.sldLrc.SetValue(self.oid - 1)
        self.OnLyricLineChange(None)
        return True

    def NextLyric(self, event):
        if self.init_lock:  return
        # 自动模式下，提早进度
        if self.auto_sending and event is not None:
            self.timeline_base-=0.5
            self.cur_t+=0.5
            UIChange(self.btnSend,label=getTimeLineStr(self.cur_t))
            return
        # 手动模式下，下一句
        if self.oid + 2 >= self.omax:
            return False
        self.sldLrc.SetValue(self.oid + 1)
        self.OnLyricLineChange(None)
        return True

    def OnSendLrcBtn(self, event):
        if self.init_lock or self.auto_sending: return
        if self.roomid is None:
            return showInfoDialog("未指定直播间", "提示")
        if not self.NextLyric(None):    return
        if self.has_trans and self.lyc_mod == 2 and self.llist[self.lid-1][2]!=self.llist[self.lid][2]:
            self.SendLyric(3)
        self.SendLyric(4)
        if self.cur_song_name!=self.last_song_name:
            self.last_song_name=self.cur_song_name
            self.LogSongName("%8s\t%s"%(self.roomid,self.cur_song_name))

    def OnClose(self, event):
        self.running = False
        self.OnStopBtn(None)
        self.Show(False)
        self.SaveConfig()
        self.SaveData()
        self.SaveTLRecords()
        self.ShowStatDialog()
        if os.path.exists("tmp.tmp"):
            try:    os.remove("tmp.tmp")
            except: pass
        if not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.pool.shutdown(wait=True)
        self.Destroy()

    def ChangeDanmuPosition(self,event):
        mode_num=len(self.modes)
        if mode_num==1: return
        trans_dict={'1':'4','4':'1'} if mode_num==2 else {'1':'4','4':'5','5':'1'}
        self.pool.submit(self.ThreadOfSetDanmuConfig,None,trans_dict[str(self.cur_mode)])

    def OnMove(self,event):
        if self.colorFrame is not None:
            self.colorFrame.Show(False)

    def OnFocus(self,event):
        panel=event.GetEventObject().GetParent()
        if self.colorFrame is not None and panel!=self.colorFrame.panel:
            self.colorFrame.Show(False)

    def OnPasteComment(self,event):
        text=wxPaste()
        if text is None:  return
        if "\n" in text or "\r" in text:
            wxCopy(re.sub("\s+"," ",text))
            self.tmp_clipboard=text
        else:
            self.tmp_clipboard=""
        event.Skip()
    
    def OnPasteSearch(self,event):
        text=wxPaste()
        if text is None:  return
        mo=re.match("歌曲名：(.*?)，歌手名：",text)
        if mo is not None:
            wxCopy(re.sub(r"\(.*?\)|（.*?）","",mo.group(1)))
            self.tmp_clipboard=text
        else:
            self.tmp_clipboard=""
        event.Skip()
    
    def FetchFromTmpClipboard(self,event):
        if self.tmp_clipboard!="":
            wxCopy(self.tmp_clipboard)
            self.tmp_clipboard=""
        event.Skip()
    
    def SetColaborMode(self,event):
        self.colabor_mode=self.cbbClbMod.GetSelection()

    def SearchLyric(self, event):
        src=event.GetEventObject().GetName()
        words = self.tcSearch.GetValue().strip().replace("\\","")
        if words in ["","*"]:   return
        if self.songSearchFrame:
            self.songSearchFrame.Destroy()
        merge_mark_ids={}
        for k,v in self.wy_marks.items():
            merge_mark_ids["W"+k]=v
        for k,v in self.qq_marks.items():
            merge_mark_ids["Q"+k]=v
        if len(words)==1:
            mark_ids = self.SearchByOneCharTag(words, merge_mark_ids)
            local_names = self.SearchByOneCharTag(words, self.locals)
        else:
            mark_ids = self.SearchByTag(words, merge_mark_ids)
            local_names = self.SearchByTag(words, self.locals)
        self.songSearchFrame = SongSearchFrame(self, src, words, mark_ids, local_names)

    def SendComment(self, event):
        pre = self.cbbComPre.GetValue()
        msg = self.tcComment.GetValue().strip()
        self.tcComment.SetFocus()
        if msg == "":
            return
        if self.roomid is None:
            return showInfoDialog("未指定直播间", "提示")
        comment = pre + msg
        if len(comment) > self.max_len*2.5:
            return showInfoDialog("弹幕内容过长", "弹幕发送失败")
        comment = self.DealWithCustomShields(comment)
        comment = self.anti_shield.deal(comment)
        suf = "】" if comment.count("【") > comment.count("】") else ""
        self.SendSplitDanmu(comment,pre,suf,0)
        self.tcComment.Clear()
        self.tcComment.SetSelection(0,0)
        self.AddHistory(msg)
        self.history_state=False

    def SaveToLocal(self,event):
        lyric=self.tcImport.GetValue().strip()
        if lyric == "":
            return showInfoDialog("歌词不能为空", "歌词保存失败")
        if lyric.count("\n") <= 4 or len(lyric) <= 50:
            return showInfoDialog("歌词内容过短", "歌词保存失败")
        name=self.tcSongName.GetValue().strip()
        if name=="":
            return showInfoDialog("歌名不能为空", "歌词保存失败")
        artists=self.tcArtists.GetValue().strip()
        tags=self.tcTags.GetValue().strip()
        has_trans=self.cbbImport2.GetSelection()==1
        self.CreateLyricFile(name,artists,tags,lyric,has_trans)


    def SetRoomid(self,roomid,name):
        if name != "":
            self.room_name=name
            self.btnRoom1.SetLabel(name)
            self.btnRoom2.SetLabel(name)
        if roomid==self.roomid: return
        if self.auto_sending: self.OnStopBtn(None)
        self.roomid=roomid
        self.playerChaser.roomId=roomid
        self.GetRoomShields(roomid)
        self.pool.submit(self.ThreadOfGetDanmuConfig)

    def GetLiveInfo(self,roomid):
        try:
            data=self.blApi.get_room_info(roomid)
            live_title=data["data"]["room_info"]["title"].replace(",","，")
            liver_name=data["data"]["anchor_info"]["base_info"]["uname"].replace(",","，")
            liver_name=re.sub(r"(?i)[_\-]*(official|channel).*","",liver_name)
            for k,v in FILENAME_TRANSFORM_RULES.items():
                liver_name=liver_name.replace(k,v)
            return liver_name,live_title
        except Exception as e:
            print("Error GetLiveInfo:",type(e),e)
            return str(roomid),""

    def GetCurrentDanmuConfig(self):
        try:
            data=self.blApi.get_user_info(self.roomid,self.cur_acc)
            if not self.LoginCheck(data):    return False
            if data["code"]==19002001:
                return showInfoDialog("房间不存在", "获取弹幕配置出错")
            config=data["data"]["property"]["danmu"]
            self.max_len=config["length"]
            self.cur_color=config["color"]
            self.cur_mode=config["mode"]
        except requests.exceptions.ConnectionError:
            return showInfoDialog("网络异常，请重试", "获取弹幕配置出错")
        except requests.exceptions.ReadTimeout:
            return showInfoDialog("获取超时，请重试", "获取弹幕配置出错")
        except Exception:
            return showInfoDialog("解析错误，请重试", "获取弹幕配置出错")
        return True

    def GetUsableDanmuConfig(self):
        try:
            data=self.blApi.get_danmu_config(self.roomid,self.cur_acc)
            if not self.LoginCheck(data):    return False
            self.colors,self.modes={},{}
            for group in data["data"]["group"]:
                for color in group["color"]:
                    if color["status"]==1:
                        self.colors[color["color"]]=color["name"]
            for mode in data["data"]["mode"]:
                if mode["status"]==1:
                    self.modes[mode["mode"]]=mode["name"]
            UIChange(self.btnDmCfg2,color="gray" if len(self.modes)==1 else "black")
        except requests.exceptions.ConnectionError:
            return showInfoDialog("网络异常，请重试", "获取弹幕配置出错")
        except requests.exceptions.ReadTimeout:
            return showInfoDialog("获取超时，请重试", "获取弹幕配置出错")
        except Exception:
            return showInfoDialog("解析错误，请重试", "获取弹幕配置出错")
        return True

    def SendDanmu(self, roomid, msg, src=0, seq=0, try_times=2):
        if msg in self.recent_danmu and len(msg) < self.max_len:
            msg+=("\u0592" if msg+"\u0594" in self.recent_danmu else "\u0594")
        self.recent_danmu.append(msg)
        self.recent_danmu.pop(0)
        try:
            data=self.blApi.send_danmu(roomid,msg,self.cur_acc)
            if not self.LoginCheck(data):
                return self.CallRecord(msg,roomid,src,"7")
            errmsg,code=data["msg"],data["code"]
            if code==10030:
                if try_times>0:
                    self.CallRecord("","0",-1,"3+")
                    wx.MilliSleep(self.send_interval_ms)
                    return self.SendDanmu(roomid,msg,src,seq,try_times-2)
                return self.CallRecord(msg,roomid,src,"3")
            if code==10031:
                return self.CallRecord(msg,roomid,src,"4")
            if code==11000:
                if try_times>0:
                    self.CallRecord("","0",-1,"5+")
                    wx.MilliSleep(self.send_interval_ms)
                    return self.SendDanmu(roomid,msg,src,seq,try_times-2)
                return self.CallRecord(msg,roomid,src,"5")
            if code!=0:
                self.LogDebug("[SendDanmu]"+str(data))
                self.CallRecord(msg,roomid,src,"x")
                return self.CallRecord("(%s)"%errmsg,"0",-1,"-")
            if errmsg=="":
                self.CallRecord(msg,roomid,src,"0")
                return True
            if errmsg in ["f","fire"]:
                self.LogShielded(msg)
                self.CallRecord(msg,roomid,src,"1")
                self.CancelFollowingDanmu(seq)
                return False
            if errmsg=="k":
                self.CallRecord(msg,roomid,src,"2")
                self.CancelFollowingDanmu(seq)
                return False
            if errmsg=="max limit":
                if try_times>0:
                    self.CallRecord("","0",-1,"6+")
                    wx.MilliSleep(self.send_interval_ms)
                    return self.SendDanmu(roomid,msg,src,seq,try_times-1)
                return self.CallRecord(msg,roomid,src,"6")
            self.LogDebug("[SendDanmu]"+"errmsg:"+errmsg)
            self.CallRecord(msg,roomid,src,"x")
            return self.CallRecord("(具体信息：%s)"%errmsg,"0",-1,"-")
        except requests.exceptions.ConnectionError as e:
            self.LogDebug("[SendDanmu]"+str(e))
            if "Remote end closed connection without response" in str(e) or "(10054," in str(e):
                if try_times>0:
                    wx.MilliSleep(200)
                    return self.SendDanmu(roomid,msg,src,seq,try_times-1)
                return self.CallRecord(msg,roomid,src,"C")
            self.pool.submit(self.ThreadOfShowMsgDlg,"网络连接出错","弹幕发送失败")
            return self.CallRecord(msg,roomid,src,"A")
        except requests.exceptions.ReadTimeout:
            return self.CallRecord(msg,roomid,src,"B")
        except Exception as e:
            self.LogDebug("[SendDanmu]"+str(e))
            self.CallRecord(msg,roomid,src,"X")
            return self.CallRecord("(具体信息：%s)"%str(e),"0",-1,"-")
    
    def CancelFollowingDanmu(self,seq):
        if not self.enable_new_send_type:   return
        while len(self.danmu_queue)>0 and self.danmu_queue[0][3]==seq:
            danmu=self.danmu_queue.pop(0)
            self.CallRecord(danmu[1],danmu[0],danmu[2],"Z")
    
    def RunRoomPlayerChaser(self,roomid,loop):
        asyncio.set_event_loop(loop)
        self.playerChaser.roomId=roomid
        if isPortUsed():
            showInfoDialog("8080端口已被占用,追帧服务启动失败","提示")
        else:
            self.playerChaser.serve(8080)
    
    def ShowStatDialog(self):
        stat_len=len(self.translate_stat)
        if not self.show_stat_on_close or stat_len==0:  return
        content="" if stat_len==1 else "本次同传共产生了%d条记录：\n"%stat_len
        for i in self.translate_stat[:3]:
            data=i.split(",")
            content+="主播：%s　　开始时间：%s　　持续时间：%s分钟\n弹幕数：%s　　总字数：%s　　平均速度：%s字/分钟\n\n"%\
                (data[2],data[0][5:-3],data[3],data[5],data[4],data[6])
        if stat_len>3:  content+="其余记录请在 logs/同传数据统计.csv 中进行查看"
        showInfoDialog(content,"同传统计数据")

    def SendLyric(self, line):
        pre = self.cbbLycPre.GetValue()
        suf = self.cbbLycSuf.GetValue()
        msg = self.llist[self.lid+line-4][2]
        message = pre + msg
        if self.shield_changed:
            message = self.DealWithCustomShields(message)
            message = self.anti_shield.deal(message)
        self.SendSplitDanmu(message,pre,suf,1)
        self.AddHistory(msg)

    def SendSplitDanmu(self, msg, pre, suf, src, seq=0):
        if seq==0:
            seq=self.danmu_seq
            self.danmu_seq+=1
        if len(msg) > self.max_len:
            for k, v in COMPRESS_RULES.items():
                msg = re.sub(k, v, msg)
        if len(msg) <= self.max_len:
            if len(msg+suf) <= self.max_len:
                self.danmu_queue.append([self.roomid,msg+suf,src,seq])
            else:
                self.danmu_queue.append([self.roomid,msg,src,seq])
            UIChange(self.btnClearQueue,label="清空 [%d]"%len(self.danmu_queue))#
            return
        spaceIdx = []
        cutIdx = self.max_len
        for i in range(len(msg)):
            if msg[i] in " 　/":
                spaceIdx.append(i)
                spaceIdx.append(i + 1)
            elif msg[i] in "（“(「":
                spaceIdx.append(i)
            elif msg[i] in "，。：！？）”…,:!?)」~":
                spaceIdx.append(i + 1)
        if len(spaceIdx) > 0:
            for idx in spaceIdx:
                if idx <= self.max_len: cutIdx = idx
        if cutIdx<self.max_len*0.5 and 1+len(msg[cutIdx:])+len(pre)>self.max_len:
             cutIdx = self.max_len
        self.danmu_queue.append([self.roomid,msg[:cutIdx],src,seq])
        UIChange(self.btnClearQueue,label="清空 [%d]"%len(self.danmu_queue))#
        if msg[cutIdx:] in [")","）","」","】","\"","”"]:  return
        self.SendSplitDanmu(pre + "…" + msg[cutIdx:],pre,suf,src,seq)


    def Mark(self,src,song_id,tags):
        if src=="wy": self.wy_marks[song_id]=tags
        else: self.qq_marks[song_id]=tags

    def Unmark(self,src,song_id):
        if src=="wy": self.wy_marks.pop(song_id,None)
        else: self.qq_marks.pop(song_id,None)

    def SearchByOneCharTag(self, char, collection):
        res = []
        for song_id in collection:
            tags = collection[song_id].split(";")
            for tag in tags:
                if tag.lower().strip()==char.lower():
                    res.append(song_id)
                    break
        return res

    def SearchByTag(self, words, collection):
        suggestions = []
        pattern=getFuzzyMatchingPattern(words)
        regex = re.compile(pattern)
        for song_id in collection:
            sug = []
            tags = collection[song_id].split(";")
            for tag in tags:
                match = regex.search(tag.lstrip())
                if match:
                    sug.append((len(match.group()), match.start()))
            if len(sug) > 0:
                sug = sorted(sug)
                suggestions.append((sug[0][0], sug[0][1], song_id))
        return [x for _, _, x in sorted(suggestions)]

    def GetRoomShields(self,roomid=None):
        room_shields={}
        if roomid is None:  roomid="none"
        for k,v in self.custom_shields.items():
            if v[2]!="" and roomid not in re.split("[,;，；]",v[2]): continue
            room_shields[k]=v[:2]
        self.room_shields=room_shields

    def DealWithCustomShields(self,msg):
        for k,v in self.room_shields.items():
            if v[0]==0 and re.search(r"\\[1-9]",k) is not None:
                msg=self.MultiDotBlock(k,msg)
            else:
                try:
                    msg=re.sub("(?i)"+" ?".join(k),v[1].replace("`","\u0592"),msg)
                except Exception as e:
                    print("[DealWithCustomShields Error]",k,e)
        return msg

    def MultiDotBlock(self,pattern,msg):
        origin_msg=msg
        try:
            pattern=re.sub(r"\\(?![1-9])","",pattern)
            groups=re.split(r"\\[1-9]",pattern)
            fills=[int(i) for i in re.findall(r"\\([1-9])",pattern)]
            n=len(fills)
            pat="(?i)" + "".join(["("+groups[i]+".*?)" for i in range(n)]) + "(%s)"%groups[n]
            repl="lambda x: (" + "+".join(["fill(x.group(1),%d)"%(len(groups[0])+int(fills[0]))] +
                ["x.group(%d)"%(i+1) for i in range(1,n+1)]) + ") if " + \
                " and ".join(["measure(x.group(%d),%d)"%(i+1,len(groups[i])+int(fills[i])) for i in range(n)]) + \
                " else x.group()"
            return re.sub(pat,eval(repl),msg)
        except Exception as e:
            print("[regex fail]",e)
            return origin_msg

    def AddHistory(self,message):
        self.recent_history.insert(0,message)
        if len(self.recent_history)>10:
            self.recent_history.pop()

    def DealWithSpam(self,info):
        msg="【检测】房间号：%s，用户名：%s，UID：%s，发言：%s"%(info["roomid"],info["uname"],info["uid"],info["msg"])
        self.pool.submit(self.LogSpam,msg,info["ts"])
        if self.auto_shield_ad:
            self.pool.submit(self.ThreadOfAdminAddRoomShield,info["roomid"],info["signature"])
        if self.auto_mute_ad:
            self.pool.submit(self.ThreadOfAdminMuteUser,info["roomid"],info["uid"],info["uname"])

    def UpdateRecord(self,msg,roomid,src,res):
        cur_time=int(time.time())
        if res=="0":
            pre,color=getTime(cur_time)+"｜","black"
        else:
            pre,color=ERR_INFO[res][0],ERR_INFO[res][1]
        self.recordFrame.AppendText("\n"+pre+msg,color)
        self.LogDanmu(msg,roomid,src,res,cur_time)
    
    def SaveTLRecords(self):
        try:
            with open("logs/recent.dat","w",encoding="utf-8") as f:
                for k,v in self.translate_records.items():
                    if v[1] is None:   continue
                    f.write("%s,%d,%d,%s\n"%(k,v[0],v[1],v[2]))
        except Exception as e: print("SaveTLRecordsOnClose Error:",type(e),e)
        for k,v in self.translate_records.items():
            if v[1] is None:    continue
            stat_res=self.StatTLRecords(k,v[0],v[1],v[2])
            self.translate_stat+=list(stat_res.values())
    
    def StatTLRecords(self,roomid,start_time,end_time,live_title):
        dir_name=self.danmu_log_dir[roomid]
        liver_name=dir_name.split("_",1)[1]
        start_date_ts=strToTs(getTime(start_time,fmt="%y-%m-%d 00:00:00"))
        records,start_ts,last_ts,word_num,danmu_count={},start_time,start_time,0,0
        for ts in range(start_date_ts,end_time+1,86400):
            date=getTime(ts,fmt="%y-%m-%d")
            try:
                with open("logs/danmu/%s/%s.log"%(dir_name,date),"r",encoding="utf-8") as f:
                    for line in f:
                        mo=re.match(r"\[00\]\[(\d{2}:\d{2}:\d{2})\](.*?【.*)",line)
                        if not mo:  continue
                        ts=strToTs(getTime(start_time,fmt="%s %s"%(date,mo.group(1))))
                        if ts<start_time or ts>end_time:    continue
                        if ts>last_ts+self.tl_stat_break_min*60:
                            if word_num>=self.tl_stat_min_word_num and danmu_count>=self.tl_stat_min_count:
                                start_str=getTime(start_ts,fmt="%Y-%m-%d %H:%M:%S")
                                duration=(last_ts-start_ts)/60
                                records[start_str]="%s,%s,%s,%.1f,%d,%d,%.1f"%(start_str,live_title,liver_name,duration,word_num,danmu_count,word_num/duration)
                            start_ts,last_ts,word_num,danmu_count=ts,ts,0,0
                        else:
                            content=re.sub("^.*?【|[【】\u0592\u0594]","",mo.group(2).strip())
                            word_num+=len(content)
                            danmu_count+=1
                            last_ts=ts
            except Exception as e:
                print("StatTLRecords ReadError:",date,type(e),e)
        if word_num>=self.tl_stat_min_word_num and danmu_count>=self.tl_stat_min_count:
            start_str=getTime(start_ts,fmt="%Y-%m-%d %H:%M:%S")
            duration=(last_ts-start_ts)/60
            records[start_str]="%s,%s,%s,%.1f,%d,%d,%.1f"%(start_str,live_title,liver_name,duration,word_num,danmu_count,word_num/duration)
        try: updateCsvFile("logs/同传数据统计.csv",0,records,2048)
        except UnicodeDecodeError:
            showInfoDialog("CSV文件被其他软件（如Excel）改动后，保存的编码错误\n请尝试将logs目录下的CSV文件移至他处\n"
            +"Excel编码解决方法：微软Excel->设置CSV保存编码为UTF-8\nWPS Excel->安装CoolCsv插件","保存同传统计结果出错")
        except Exception as e:
            print("StatTLRecords WriteError:",roomid,type(e),e)
        finally:
            return records

    def LogDanmu(self,msg,roomid,src,res,cur_time):
        if roomid=="0" or src<0: return
        if roomid in self.danmu_log_dir.keys():
            dir_name=self.danmu_log_dir[roomid]
        else:
            liver_name,_=self.GetLiveInfo(roomid)
            dir_name="%s_%s"%(roomid,liver_name)
            self.danmu_log_dir[roomid]=dir_name
            os.mkdir("logs/danmu/%s"%dir_name)
        try:
            path="logs/danmu/%s/%s.log"%(dir_name,getTime(cur_time,fmt="%y-%m-%d"))
            with open(path,"a",encoding="utf-8") as f:
                f.write("[%d%s][%s]%s\n"%(src,res,getTime(cur_time),msg))
        except Exception as e:
            print("[Log Error]",type(e),e)
        if src==0 and "【" in msg and res=="0":
            if roomid in self.translate_records.keys():
                self.translate_records[roomid][1]=cur_time
            else:
                _,live_title=self.GetLiveInfo(roomid)
                self.translate_records[roomid]=[cur_time,cur_time,live_title]
    
    def LogShielded(self,msg):
        try:
            path="logs/shielded/SHIELDED_%s.log"%getTime(fmt="%y-%m")
            with open(path,"a",encoding="utf-8") as f:
                f.write("%s｜%s\n"%(getTime(fmt="%m-%d %H:%M"),msg))
        except: pass

    def LogSpam(self,msg,ts=None):
        try:
            path="logs/antiSpam/ANTISPAM_%s.log"%getTime(ts,fmt="%y-%m")
            with open(path,"a",encoding="utf-8") as f:
                f.write("%s｜%s\n"%(getTime(ts,fmt="%m-%d %H:%M:%S"),msg))
        except: pass
    
    def LogSongName(self,msg):
        try:
            path="logs/lyric/LYRIC_%s.log"%getTime(fmt="%y-%m")
            with open(path,"a",encoding="utf-8") as f:
                f.write("%s｜%s\n"%(getTime(fmt="%m-%d %H:%M"),msg))
        except: pass

    def LogDebug(self,msg):
        try:
            path="logs/debug/DEBUG_%s.log"%getTime(fmt="%y-%m")
            with open(path,"a",encoding="utf-8") as f:
                f.write("%s｜%s\n"%(getTime(fmt="%m-%d %H:%M"),msg))
        except: pass

    def LoginCheck(self,res):
        if res["code"]==-101 or "登录" in res["message"]:
            self.OnStopBtn(None)
            return showInfoDialog("账号配置不可用，请修改Cookie配置\n"+
                "方法一：点击“应用设置”按钮，右键“账号切换”处的按钮进行修改\n"+
                "方法二：关闭工具后，打开工具目录下的config.txt，修改cookie项", "错误")
        return True
     
    def CallRecord(self,msg,roomid,src,res):
        wx.CallAfter(pub.sendMessage,"record",msg=msg,roomid=roomid,src=src,res=res)
        return False
    
    def SaveAccountInfo(self,acc_no,acc_name,cookie):
        self.account_names[acc_no]=acc_name
        self.cookies[acc_no]=self.blApi.update_cookie(cookie,acc_no)
        if acc_no==self.cur_acc:
            self.SetTitle("LyricDanmu %s - %s"%(LD_VERSION,acc_name))
    
    def SwitchAccount(self,acc_no):
        acc_name=self.account_names[acc_no]
        if acc_no==self.cur_acc:    return
        self.cur_acc=acc_no
        self.SetTitle("LyricDanmu %s - %s"%(LD_VERSION,acc_name))
        if self.roomid is not None:
            self.pool.submit(self.ThreadOfGetDanmuConfig)


    def GetLyricData(self,lrcO):
        listO = []
        for o in lrcO.strip().split("\n"):
            for f in splitTnL(o):    listO.append(f)
        return sorted(listO, key=lambda f:f[1])

    def GetMixLyricData(self, lrcO, lrcT):
        dictT,dictO,res = {},{},[]
        for t in lrcT.strip().split("\n"):
            for f in splitTnL(t):    dictT[f[3]]=f
        tempT = sorted(dictT.values(), key=lambda f:f[1])
        for o in lrcO.strip().split("\n"):
            for f in splitTnL(o):    dictO[f[3]]=f
        listO,olen = sorted(dictO.values(), key=lambda f:f[1]),len(dictO)
        td,tlT,tlO = [5]*olen,[None]*olen,[f[1] if f[2]!="" else -5 for f in listO]
        for f in tempT:
            for i in range(olen):
                dif=abs(f[1]-tlO[i])
                if dif<td[i] and listO[i][2]!="":   td[i],tlT[i]=dif,f[3]
        for i in range(olen):
            res.append(listO[i])
            res.append(listO[i] if tlT[i] is None or re.match("不得翻唱|^//$",dictT[tlT[i]][2]) else dictT[tlT[i]])
        return res

    def FilterLyric(self,fs):
        res,fslen,prev_empty,i=[],len(fs),False,0
        while i<fslen:
            if re.search(LYRIC_IGNORE_RULES,fs[i][2]):
                i += 2 if self.has_trans else 1
                continue
            if fs[i][2] != "":
                res.append(fs[i])
                prev_empty = False
            else:
                if not prev_empty:
                    res.append(["",fs[i][1],"",""])
                    if self.has_trans:
                        res.append(["",fs[i][1],"",""])
                    prev_empty = True
                i+=1
                continue
            i+=1
            if self.has_trans and i<fslen:
                res.append(fs[i])
                i+=1
        return res

    def MergeSingleLyric(self,fs):
        fslen,usedlen=len(fs),len(self.cbbLycPre.GetValue().lstrip())+1
        res,base_tl,prev_tl,content,new_line=[],0,100,"",True
        for i in range(fslen):
            tl,c=fs[i][1],fs[i][2]
            if c=="":   continue
            if tl-prev_tl>=LYRIC_EMPTY_LINE_THRESHOLD_S:
                if not new_line:    res.append([getTimeLineStr(base_tl,1),base_tl,content,""])
                res.append(["",prev_tl+3,"",""])
                new_line=True
            prev_tl=tl
            if new_line:
                base_tl,content,new_line=tl,c,False
                continue
            if tl-base_tl<=self.lyric_merge_threshold_s and len(content+c)+usedlen<=self.max_len:
                content+="　"+c
                continue
            res.append([getTimeLineStr(base_tl,1),base_tl,content,""])
            base_tl,content=tl,c
        if not new_line:    res.append([getTimeLineStr(base_tl,1),base_tl,content,""])
        return res

    def MergeMixLyric(self,fs):
        fslen,usedlen=len(fs),len(self.cbbLycPre.GetValue().lstrip())+1
        res,base_tl,prev_tl,content_o,content_t,new_line=[],0,100,"","",True
        for i in range(0,fslen,2):
            tl,co,ct=fs[i+1][1],fs[i][2],fs[i+1][2]
            if ct=="":   continue
            if tl-prev_tl>=LYRIC_EMPTY_LINE_THRESHOLD_S:
                if not new_line:
                    res.append([getTimeLineStr(base_tl,1),base_tl,content_o,""])
                    res.append([getTimeLineStr(base_tl,1),base_tl,content_t,""])
                res.append(["",prev_tl+3,"",""])
                res.append(["",prev_tl+3,"",""])
                new_line=True
            prev_tl=tl
            if new_line:
                base_tl,content_o,content_t,new_line=tl,co,ct,False
                continue
            if tl-base_tl<=self.lyric_merge_threshold_s and len(content_t+ct)+usedlen<=self.max_len:
                content_o,content_t=content_o+"　"+co,content_t+"　"+ct
                continue
            res.append([getTimeLineStr(base_tl,1),base_tl,content_o,""])
            res.append([getTimeLineStr(base_tl,1),base_tl,content_t,""])
            base_tl,content_o,content_t=tl,co,ct
        if not new_line:
            res.append([getTimeLineStr(base_tl,1),base_tl,content_o,""])
            res.append([getTimeLineStr(base_tl,1),base_tl,content_t,""])
        return res

    def RecvLyric(self,data):
        self.init_lock = False
        self.shield_changed = False
        self.OnStopBtn(None)
        self.sldLrc.Show(True)
        self.has_trans=data["has_trans"]
        self.cur_song_name=data["name"]
        self.has_timeline=True
        so=re.search(r"\[(\d+):(\d+)(\.\d*)?\]",data["lyric"])
        if so is None:
            tmpList=data["lyric"].strip().split("\n")
            tmpData=[["", -1, i.strip(), ""] for i in tmpList]
            self.has_timeline=False
        elif self.has_trans and data["src"]!="local":
            tmpData=self.GetMixLyricData(data["lyric"],data["tlyric"])
        else:
            tmpData=self.GetLyricData(data["lyric"])
        tmpData=self.FilterLyric(tmpData)
        self.lyric_raw="\r\n".join([i[2] for i in tmpData])
        self.lyric_raw_tl="\r\n".join([i[3]+i[2] for i in tmpData])
        if self.has_timeline and self.enable_lyric_merge:
            tmpData=self.MergeMixLyric(tmpData) if self.has_trans else self.MergeSingleLyric(tmpData)
        lyrics="\r\n".join([i[2] for i in tmpData])
        for k, v in HTML_TRANSFORM_RULES.items():
            lyrics = re.sub(k, v, lyrics)
            self.lyric_raw = re.sub(k,v,self.lyric_raw)
            self.lyric_raw_tl = re.sub(k,v,self.lyric_raw_tl)
        lyrics = self.DealWithCustomShields(lyrics)
        lyrics = self.anti_shield.deal(lyrics)
        lyric_list=lyrics.split("\r\n")
        for i in range(len(lyric_list)):
            tmpData[i][2]=lyric_list[i]
        if self.add_song_name and data["name"]!="" and len(tmpData)>0:
            tl=(tmpData[-1][1]+3) if tmpData[-1][1]>=0 else -1
            tl_str=getTimeLineStr(tl,1) if tl>=0 else ""
            name_info=self.DealWithCustomShields("歌名："+data["name"])
            name_info=self.anti_shield.deal(name_info)
            tmpData.append(["",tl,"",""])
            tmpData.append([tl_str,tl,name_info,""])
            if self.has_trans:
                tmpData.append([tl_str,tl,name_info,""]) 
        tmpData.insert(0,["",-1,"<BEGIN>",""])
        tmpData.append(["",-1,"<END>",""])
        if self.has_trans:
            tmpData.insert(0,["",-1,"<BEGIN>",""])
            tmpData.append(["",-1,"<END>",""])
        self.llist=tmpData
        self.lmax = len(self.llist)
        self.olist = []
        i = 0
        while i < self.lmax:
            if self.llist[i][2] != "":
                self.olist.append(i)
                i = i + 2 if self.has_trans else i + 1
            else:
                i += 1
        self.omax = len(self.olist)
        self.timelines=[]
        for i in self.olist:
            self.timelines.append(self.llist[i][1])
        self.oid = 0
        self.lid = self.olist[self.oid]
        if self.has_trans and self.lyc_mod > 0:
            self.lid += 1
        self.sldLrc.SetRange(0, self.omax - 2)
        self.sldLrc.SetValue(self.oid)
        self.lblCurLine.SetLabel(str(self.oid))
        self.lblMaxLine.SetLabel(str(self.omax - 2))
        self.RefreshLyric()
        self.show_lyric=True
        self.show_import=False
        self.ResizeUI()
        if self.has_timeline:
            self.btnAutoSend.SetLabel("自动 ▶")
            self.btnAutoSend.Enable()
            self.btnStopAuto.Enable()
        else:
            self.btnAutoSend.SetLabel("无时间轴")
            self.btnAutoSend.Disable()
            self.btnStopAuto.Disable()

    def RefreshLyric(self):
        if self.init_lock:  return
        offset=int(self.has_trans and self.lyc_mod>0) - 4 
        for i in range(11):
            lid = self.olist[self.oid+self.lyric_offset] + i +offset
            if 0 <= lid < self.lmax:
                self.lblTimelines[i].SetLabel(self.llist[lid][0])
                self.lblLyrics[i].SetLabel(self.llist[lid][2])
            else:
                self.lblTimelines[i].SetLabel("")
                self.lblLyrics[i].SetLabel("")


    def CheckFile(self):
        dirs=("songs","logs","logs/danmu","logs/lyric","logs/debug","logs/shielded")
        for dir in dirs:
            if not os.path.exists(dir): os.mkdir(dir)
        if not os.path.exists("config.txt"):
            self.SaveConfig()
        if not os.path.exists("rooms.txt"):
            with open("rooms.txt", "w", encoding="utf-8") as f:     f.write("")
        if not os.path.exists("marks_wy.txt"):
            with open("marks_wy.txt", "w", encoding="utf-8") as f:  f.write("")
        if not os.path.exists("marks_qq.txt"):
            with open("marks_qq.txt", "w", encoding="utf-8") as f:  f.write("")
        if not os.path.exists("shields.txt"):
            with open("shields.txt", "w", encoding="utf-8") as f:   f.write("")
        if not os.path.exists("shields_global.dat"):
            with open("shields_global.dat", "w", encoding="utf-8") as f:    f.write("")
        if not os.path.exists("custom_texts.txt"):
            with open("custom_texts.txt", "w", encoding="utf-8") as f:  f.write(DEFAULT_CUSTOM_TEXT)
        if not os.path.exists("logs/recent.dat"):
            with open("logs/recent.dat", "w", encoding="utf-8") as f:   f.write("")
        if not os.path.exists("logs/同传数据统计.csv"):
            with open("logs/同传数据统计.csv", "w", encoding="utf-8-sig") as f:
                f.write("同传开始时间,直播标题,主播,持续时间(分钟),同传字数,同传条数,速度(字/分钟)\n")

    def ReadFile(self):
        try:
            with open("config.txt", "r", encoding="utf-8") as f:
                for line in f:
                    if "=" not in line:     continue
                    sp = line.split("=", 1)
                    k,v=sp[0].strip().lower(),sp[1].strip()
                    if k == "默认歌词前缀":
                        self.prefix = v
                    elif k == "默认歌词后缀":
                        self.suffix = v
                    elif k == "歌词前缀备选":
                        self.prefixs = v.split(",")
                    elif k == "歌词后缀备选":
                        self.suffixs = v.split(",")
                    elif k == "歌词高亮显示":
                        self.lyric_offset = 0 if "待发送" not in v else 1
                    elif k == "启用歌词合并":
                        self.enable_lyric_merge = v.lower()=="true"
                    elif k == "歌词合并阈值":
                        merge_th = int(v)
                        if 3000 <= merge_th <= 8000:
                            self.lyric_merge_threshold_s=0.001*merge_th
                    elif k == "曲末显示歌名":
                        self.add_song_name = v.lower()=="true"
                    elif k == "新版发送机制":
                        self.enable_new_send_type = v.lower()=="true"
                    elif k == "最低发送间隔":
                        interval = int(v)
                        if 500 <= interval <= 1500:
                            self.send_interval_ms = interval
                            send_interval_check=True
                        else:
                            send_interval_check=False
                    elif k == "请求超时阈值":
                        tm_out = int(v)
                        if 2000 <= tm_out <= 10000:
                            self.timeout_s=0.001*tm_out
                    elif k == "默认搜索来源":
                        self.default_src = "wy" if "qq" not in v.lower() else "qq"
                    elif k == "歌曲搜索条数":
                        search_num = int(v)
                        if 5 <= search_num <= 30:
                            self.search_num=search_num
                    elif k == "每页显示条数":
                        page_limit = int(v)
                        if 5 <= page_limit <= 8:
                            self.page_limit=page_limit
                    elif k == "默认展开歌词":
                        self.init_show_lyric = v.lower()=="true"
                    elif k == "忽略系统代理":
                        self.no_proxy = v.lower()=="true"
                    elif k == "账号标注":
                        self.account_names[0] = "账号1" if v=="" else v
                    elif k == "账号标注2":
                        self.account_names[1] = "账号2" if v=="" else v
                    elif k == "cookie":
                        self.cookies[0] = v
                    elif k == "cookie2":
                        self.cookies[1] = v
                    elif k == "同传中断阈值":
                        self.tl_stat_break_min = min(max(int(v),5),30)
                    elif k == "最低字数要求":
                        self.tl_stat_min_word_num = max(int(v),0)
                    elif k == "最低条数要求":
                        self.tl_stat_min_count = max(int(v),2)
                    elif k == "退出时显示统计":
                        self.show_stat_on_close = v.lower()=="true"
                    elif k == "默认双前缀模式":
                        self.init_two_prefix = v.lower()=="true"
                    elif k == "默认打开记录":
                        self.init_show_record = v.lower()=="true"
                    elif k == "彩色弹幕记录":
                        self.enable_rich_record = v.lower()=="true"
                    elif k == "弹幕记录字号":
                        self.record_fontsize = min(max(int(v),9),16)
                if not send_interval_check:
                    self.send_interval_ms = 750 if self.enable_new_send_type else 1050
        except Exception:
            return showInfoDialog("读取config.txt失败", "启动出错")
        try:
            with open("rooms.txt", "r", encoding="utf-8") as f:
                for line in f:
                    mo=re.match(r"\s*(\d+)\s+(.+)",line)
                    if mo is not None:
                        self.rooms[mo.group(1)] = mo.group(2).rstrip()
        except Exception:
            showInfoDialog("读取rooms.txt失败", "提示")
        try:
            with open("marks_wy.txt", "r", encoding="utf-8") as f:
                for line in f:
                    mo = re.match(r"\s*(\d+)\s+(.+)", line)
                    if mo is not None:
                        self.wy_marks[mo.group(1)] = mo.group(2).rstrip()
        except Exception:
            showInfoDialog("读取marks_wy.txt失败", "提示")
        try:
            with open("marks_qq.txt", "r", encoding="utf-8") as f:
                for line in f:
                    mo = re.match(r"\s*(\d+)\s+(.+)", line)
                    if mo is not None:
                        self.qq_marks[mo.group(1)] = mo.group(2).rstrip()
        except Exception:
            showInfoDialog("读取marks_qq.txt失败", "提示")
        try:
            with open("shields.txt", "r", encoding="utf-8") as f:
                for line in f:
                    mo = re.match(r"\s*(0|1)\s+(\S+)\s+(\S+)\s*(\S*)", line)
                    if mo is None:  continue
                    if re.search(r"\\(?![1-9])|[\(\)\[\]\{\}\.\+\*\^\$\?\|]",mo.group(2)) is not None:  continue
                    if mo.group(1)=="0":
                        if "\\" in mo.group(2): rep=re.sub(r"\\([1-9])",lambda x: int(x.group(1))*"`",mo.group(2),count=1)
                        else:   rep=mo.group(2)[0]+"`"+mo.group(2)[1:]
                    else:   rep=mo.group(3).replace("·","`").replace("\\","\\\\")
                    rooms=mo.group(4)
                    if mo.group(2) in self.custom_shields.keys(): #合并房间列表
                        old_rooms=self.custom_shields[mo.group(2)][2]
                        rooms=(old_rooms+","+rooms) if old_rooms!="" and rooms!="" else ""
                    self.custom_shields[mo.group(2)]=[int(mo.group(1)),rep,rooms]
        except Exception:
            showInfoDialog("读取shields.txt失败", "提示")
        try:
            scope= {"modified_time":0,"words":[],"rules":{}}
            with open("shields_global.dat","r",encoding="utf-8") as f:
                exec(f.read(),scope)
            self.anti_shield=BiliLiveAntiShield(scope["rules"],scope["words"])
            self.need_update_global_shields=time.time()-scope["modified_time"]>GLOBAL_SHIELDS_UPDATE_INTERVAL_S
        except Exception:
            showInfoDialog("读取shields_global.dat失败", "提示")
        try:
            cur_time=int(time.time())
            with open("logs/recent.dat", "r", encoding="utf-8") as f:
                for line in f:
                    mo = re.match(r"(\d+),(\d+),(\d+),(.*)", line)
                    if mo and cur_time-int(mo.group(3))<=self.tl_stat_break_min*60:
                        self.translate_records[mo.group(1)]=[int(mo.group(2)),None,mo.group(4).strip()]
        except Exception:
            showInfoDialog("读取logs/recent.dat失败", "提示")
        # 读取弹幕记录目录名称列表
        for dir_name in os.listdir("logs/danmu"):
            if os.path.isfile("logs/danmu/"+dir_name):    continue
            mo = re.match(r"^(\d+)_.+$",dir_name)
            if mo: self.danmu_log_dir[mo.group(1)]=mo.group()
        self.ReadCustomTexts()
        self.ReadLocalSongs()
        return True

    def ReadCustomTexts(self):
        default_data={
            "title":"(右键编辑)",
            "content":"",
        }
        try:
            collection = xml.dom.minidom.parse("custom_texts.txt").documentElement
            texts = collection.getElementsByTagName("text")
        except Exception:
            return showInfoDialog("读取custom_texts.txt失败", "提示")
        index=0
        for text in texts:
            data=default_data.copy()
            if text.hasAttribute("title") and text.getAttribute("title").strip()!="":
                data["title"]=text.getAttribute("title")
            data["content"]=text.childNodes[0].data
            self.custom_texts.append(data)
            index+=1
            if index>=4:    break
        while index<4:
            self.custom_texts.append(default_data.copy())
            index+=1

    def ConvertLocalSong(self,filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                tmpContent=f.read().strip()
            if not re.match("<name>",tmpContent):   return
            content="<local>\n"+tmpContent+"\n</local>"
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return xml.dom.minidom.parseString(content)
        except Exception as e:
            print("ConvertLocalSong:",filepath,type(e),str(e))

    def ReadLocalSongs(self):
        fileList = os.listdir("songs")
        for file in fileList:
            filepath = "songs/" + file
            if not os.path.isfile(filepath):    continue
            DOMTree = None
            try:    DOMTree = xml.dom.minidom.parse(filepath)
            except xml.parsers.expat.ExpatError:
                DOMTree = self.ConvertLocalSong(filepath)
            except Exception as e:
                print("ReadLocalSongs(1):",filepath,type(e),str(e))
            if DOMTree is None:     continue
            try:
                localSong = DOMTree.documentElement
                name=re.sub(r";|；","",getNodeValue(localSong,"name"))
                artists=re.sub(r";|；","/",getNodeValue(localSong,"artists"))
                lang="双语" if getNodeValue(localSong,"type") == "双语" else "单语"
                tags=getNodeValue(localSong,"tags")
                self.locals[file]=name+";"+artists+";"+lang+";"+tags
            except Exception as e:
                print("ReadLocalSongs(2):",filepath,type(e),str(e))

    def CreateLyricFile(self,name,artists,tags,lyric,has_trans):
        filename=re.sub(r";|；","",name)
        lang="双语" if has_trans else "单语"
        for k,v in FILENAME_TRANSFORM_RULES.items():
            filename=filename.replace(k,v)
        tags = re.sub(r"\r?\n|；", ";", tags)
        tags = re.sub(r";+", ";", tags)
        if os.path.exists("songs/%s.txt"%filename):
            dlg = wx.MessageDialog(None, "歌词文件已存在，是否覆盖已有文件?", "提示", wx.YES_NO)
            if dlg.ShowModal()!=wx.ID_YES:
                dlg.Destroy()
                return False
            dlg.Destroy()
        try:
            with open("songs/%s.txt"%filename,"w",encoding="utf-8") as f:
                f.write("<local>\n")
                f.write("<name>" + name + "</name>\n")
                f.write("<artists>" + artists + "</artists>\n")
                f.write("<tags>" + tags + "</tags>\n")
                f.write("<type>" + lang + "</type>\n")
                f.write("<lyric>\n" + lyric +"\n</lyric>\n")
                f.write("</local>")
            self.locals[filename+".txt"]=name+";"+artists+";"+lang+";"+tags
            showInfoDialog("歌词保存成功", "提示")
            return True
        except:
            return showInfoDialog("文件写入失败", "歌词保存失败")

    def ShowLocalInfo(self,file):
        try:
            localSong =xml.dom.minidom.parse("songs/"+file).documentElement
            lyric=getNodeValue(localSong,"lyric")
            raw_info=self.locals[file]
            info=raw_info.split(";",3)
            trans_id = 1 if info[2] == "双语" else 0
            self.tcSongName.SetValue(info[0])
            self.tcArtists.SetValue(info[1])
            self.cbbImport.SetSelection(trans_id)
            self.cbbImport2.SetSelection(trans_id)
            self.tcTags.SetValue(info[3].replace(";","\n"))
            self.tcImport.SetValue(lyric)
            self.show_lyric=True
            self.show_import=True
            self.ResizeUI()
            return True
        except Exception as e:
            print("ShowLocalInfo:",str(e))
            return False

    def SaveConfig(self):
        def titleLine(title): return "%s\n#%s#\n%s\n"%("-"*15,title,"-"*15)
        try:
            with open("config.txt", "w", encoding="utf-8") as f:
                f.write(titleLine("歌词显示配置"))
                f.write("默认歌词前缀=%s\n" % self.prefix)
                f.write("默认歌词后缀=%s\n" % self.suffix)
                f.write("歌词前缀备选=%s\n" % ",".join(self.prefixs))
                f.write("歌词后缀备选=%s\n" % ",".join(self.suffixs))
                f.write("歌词高亮显示=%s\n" % ("当前播放行" if self.lyric_offset==0 else "待发送歌词"))
                f.write("启用歌词合并=%s\n" % self.enable_lyric_merge)
                f.write("歌词合并阈值=%d\n" % int(1000*self.lyric_merge_threshold_s))
                f.write("曲末显示歌名=%s\n" % self.add_song_name)
                f.write(titleLine("歌词搜索配置"))
                f.write("默认搜索来源=%s\n" % ("网易云音乐" if self.default_src=="wy" else "QQ音乐"))
                f.write("歌曲搜索条数=%d\n" % self.search_num)
                f.write("每页显示条数=%d\n" % self.page_limit)
                f.write(titleLine("弹幕发送配置"))
                f.write("忽略系统代理=%s\n" % self.no_proxy)
                f.write("新版发送机制=%s\n" % self.enable_new_send_type)
                f.write("最低发送间隔=%d\n" % self.send_interval_ms)
                f.write("请求超时阈值=%d\n" % int(1000*self.timeout_s))
                f.write(titleLine("同传统计配置"))
                f.write("同传中断阈值=%d\n" % self.tl_stat_break_min)
                f.write("最低字数要求=%d\n" % self.tl_stat_min_word_num)
                f.write("最低条数要求=%d\n" % self.tl_stat_min_count)
                f.write("退出时显示统计=%s\n" % self.show_stat_on_close)
                f.write(titleLine("弹幕记录配置"))
                f.write("彩色弹幕记录=%s\n" % self.enable_rich_record)
                f.write("弹幕记录字号=%d\n" % self.record_fontsize)
                f.write(titleLine("默认启动配置"))
                f.write("默认展开歌词=%s\n" % self.init_show_lyric)
                f.write("默认打开记录=%s\n" % self.init_show_record)
                f.write("默认双前缀模式=%s\n" % self.init_two_prefix)
                f.write(titleLine("账号信息配置"))
                f.write("账号标注=%s\n" % self.account_names[0])
                f.write("cookie=%s\n" % self.cookies[0])
                f.write("账号标注2=%s\n" % self.account_names[1])
                f.write("cookie2=%s\n" % self.cookies[1])
        except Exception as e:
            print("SaveConfig:",type(e),e)

    def SaveData(self):
        try:
            with open("rooms.txt", "w", encoding="utf-8") as f:
                for roomid in self.rooms:
                    f.write("%-15s%s\n" % (roomid, self.rooms[roomid]))
        except: pass
        try:
            with open("marks_wy.txt", "w", encoding="utf-8") as f:
                for song_id in self.wy_marks:
                    f.write("%-15s%s\n" % (song_id, self.wy_marks[song_id]))
        except: pass
        try:
            with open("marks_qq.txt", "w", encoding="utf-8") as f:
                for song_id in self.qq_marks:
                    f.write("%-15s%s\n" % (song_id, self.qq_marks[song_id]))
        except: pass
        try:
            with open("shields.txt", "w", encoding="utf-8") as f:
                for k,v in self.custom_shields.items():
                    f.write("%d %s %s %s\n" % (v[0],k,v[1].replace("\\\\","\\"),v[2]))
        except: pass
        try:
            with open("custom_texts.txt", "w", encoding="utf-8") as f:
                f.write("<texts>\n")
                for text in self.custom_texts:
                    f.write("<text title=\"%s\">\n%s\n</text>\n"%(text["title"],text["content"].strip()))
                f.write("</texts>")
                f.flush()
        except: pass


if __name__ == '__main__':
    app = wx.App(False)
    frame = LyricDanmu(None)
    app.MainLoop()
