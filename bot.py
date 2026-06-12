
import requests
import os
import psutil
import sys
import jwt
import pickle
import json
import binascii
import time
import urllib3
import xKEys
import base64
import datetime
import re
import socket
import threading
import asyncio
import logging
from datetime import datetime, timedelta
from google.protobuf.timestamp_pb2 import Timestamp
from concurrent.futures import ThreadPoolExecutor
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ================= [ إعدادات المتغيرات البيئية ] =================
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# جلب آيدي الماستر وتحويله إلى رقم (Integer)
master_id_env = os.environ.get("MASTER_ADMIN_ID")
MASTER_ADMIN_ID = int(master_id_env) if master_id_env and master_id_env.isdigit() else 0

# جلب قائمة الأدمنز وتفكيكها من نص مفصول بفواصل إلى قائمة أرقام
admin_ids_env = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in admin_ids_env.split(",") if x.strip().isdigit()]
# =================================================================

try:
    from protobuf_decoder.protobuf_decoder import Parser
except ImportError:
    class Parser:
        @staticmethod
        def parse(data):
            return {"error": "protobuf_decoder not installed"}
    print("⚠️ تنبيه: protobuf_decoder غير متوفر - سيتم استخدام Parser افتراضي")

from stravex_utils import *
from stravex_utils import xSEndMsg, Auth_Chat
from xHeaders import *
from stravex_spam import openroom, spmroom

import telebot
from telebot.types import Message

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


GROUPS_FILE = "activated_groups.json"
MAINTENANCE_FILE = "maintenance.json"

ACTIVATED_GROUPS = {}

maintenance_mode = False

def load_activated_groups():
    global ACTIVATED_GROUPS
    try:
        if os.path.exists(GROUPS_FILE):
            with open(GROUPS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    ACTIVATED_GROUPS = {k: v for k, v in data.items()}
        print(f"✅ تم تحميل {len(ACTIVATED_GROUPS)} مجموعة مفعلة")
    except Exception as e:
        print(f"⚠️ خطأ في تحميل المجموعات: {e}")
        ACTIVATED_GROUPS = {}

def save_activated_groups():
    try:
        with open(GROUPS_FILE, "w", encoding="utf-8") as f:
            json.dump(ACTIVATED_GROUPS, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"❌ خطأ في حفظ المجموعات: {e}")
        return False

def load_maintenance_status():
    global maintenance_mode
    try:
        if os.path.exists(MAINTENANCE_FILE):
            with open(MAINTENANCE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                maintenance_mode = data.get("maintenance_mode", False)
        print(f"✅ حالة الصيانة: {'مفعلة' if maintenance_mode else 'غير مفعلة'}")
    except Exception as e:
        print(f"⚠️ خطأ في تحميل حالة الصيانة: {e}")
        maintenance_mode = False

def save_maintenance_status(status):
    global maintenance_mode
    maintenance_mode = status
    try:
        with open(MAINTENANCE_FILE, "w", encoding="utf-8") as f:
            json.dump({"maintenance_mode": status}, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"❌ خطأ في حفظ حالة الصيانة: {e}")
        return False

load_activated_groups()
load_maintenance_status()

bot = telebot.TeleBot(BOT_TOKEN)

try:
    bot_info = bot.get_me()
    print(f"✅ البوت متصل: @{bot_info.username}")
except Exception as e:
    print(f"❌ خطأ في الاتصال بالبوت: {e}")

connected_clients = {}
connected_clients_lock = threading.Lock()

active_spam_targets = {}
active_spam_lock = threading.Lock()

ACCOUNTS = []

def load_accounts_from_file(filename="accounts.txt"):
    accounts = []
    try:
        with open(filename, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if line and not line.startswith("#"):
                    if ":" in line:
                        parts = line.split(":")
                        if len(parts) >= 2:
                            account_id = parts[0].strip()
                            password = parts[1].strip()
                            accounts.append({'id': account_id, 'password': password})
                    else:
                        accounts.append({'id': line.strip(), 'password': ''})
        print(f"✅ تم تحميل {len(accounts)} حساب من {filename}")
    except FileNotFoundError:
        print(f"⚠️ ملف {filename} غير موجود!")
    except Exception as e:
        print(f"❌ حدث خطأ أثناء قراءة الملف: {e}")
    
    return accounts

ACCOUNTS = load_accounts_from_file()
print(f"📊 إجمالي الحسابات: {len(ACCOUNTS)}")

def is_admin(user_id):
    return user_id in ADMIN_IDS

def format_remaining_time(expiry_time):
    remaining = int(expiry_time - time.time())
    if remaining <= 0:
        return "⛔ انتهت الصلاحية"

    days = remaining // 86400
    hours = (remaining % 86400) // 3600
    minutes = ((remaining % 86400) % 3600) // 60
    seconds = remaining % 60

    parts = []
    if days > 0:
        parts.append(f"{days} يوم")
    if hours > 0:
        parts.append(f"{hours} ساعة")
    if minutes > 0:
        parts.append(f"{minutes} دقيقة")
    parts.append(f"{seconds} ثانية")

    return " ".join(parts)

def check_expired_groups():
    while True:
        try:
            now = time.time()
            expired = [gid for gid, exp in ACTIVATED_GROUPS.items() if exp <= now]
            
            for group_id in expired:
                del ACTIVATED_GROUPS[group_id]
                print(f"⏹️ تم إزالة المجموعة {group_id} - انتهت صلاحيتها")
            
            if expired:
                save_activated_groups()
        except Exception as e:
            print(f"⚠️ خطأ في التحقق من المجموعات منتهية الصلاحية: {e}")
        
        time.sleep(60)

def send_message_to_all_groups(message_text):
    for group_id in list(ACTIVATED_GROUPS.keys()):
        try:
            bot.send_message(group_id, message_text, parse_mode="Markdown")
            time.sleep(1)
        except telebot.apihelper.ApiTelegramException as e:
            if "chat not found" in str(e) or "bot was kicked from the group chat" in str(e):
                print(f"⚠️ فشل إرسال رسالة إلى المجموعة {group_id}: البوت ليس عضواً. سيتم حذفها.")
                del ACTIVATED_GROUPS[group_id]
                save_activated_groups()
            else:
                print(f"⚠️ فشل إرسال رسالة إلى المجموعة {group_id}: {e}")

def is_group_activated(chat_id):
    chat_id_str = str(chat_id)
    
    if chat_id_str in ACTIVATED_GROUPS:
        expiry_time = ACTIVATED_GROUPS[chat_id_str]
        if expiry_time > time.time():
            return True
        else:
            del ACTIVATED_GROUPS[chat_id_str]
            save_activated_groups()
            return False
    
    return False

def is_private_chat(message):
    return message.chat.type == "private"

def check_group_access(message):
    chat_id = message.chat.id
    
    if is_private_chat(message):
        if is_admin(message.from_user.id):
            return True, None
        else:
            return False, "private_no_access"
    
    if is_group_activated(chat_id):
        return True, None
    else:
        return False, "group_not_activated"

def bold_decor(text: str) -> str:
    """تزيين النص بخط عريض وزخرفة خفيفة"""
    return f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n*{text}*\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯"

def fancy_text(core: str) -> str:
    return f"🔥 *『 {core} 』* 🔥"

def access_denied_message(message, reason):
    chat_id = message.chat.id
    
    if reason == "private_no_access":
        bot.reply_to(
            message,
            bold_decor("⛔ وصول مرفوض\n\nهذا البوت لا يعمل في المحادثات الخاصة.\nللاستخدام، يرجى إضافة البوت إلى مجموعة وتفعيلها.\n\nللتواصل مع المطور: @tp_qw1"),
            parse_mode="Markdown"
        )
    
    elif reason == "group_not_activated":
        expiry_info = ""
        if str(chat_id) in ACTIVATED_GROUPS:
            expiry = ACTIVATED_GROUPS[str(chat_id)]
            if expiry <= time.time():
                expiry_info = "\n⚠️ انتهت صلاحية التفعيل"

        bot.reply_to(
            message,
            bold_decor(f"⛔ البوت غير مفعل في هذه المجموعة{expiry_info}\n\n🆔 معرف المجموعة: {chat_id}\n\nلتفعيل البوت، يرجى التواصل مع المطور:\n👤 @tp_qw1\n\n📌 يرجى إرسال معرف المجموعة للمطور لتفعيلها."),
            parse_mode="Markdown"
        )

def require_access(func):
    def wrapper(message, *args, **kwargs):
        if maintenance_mode and not is_admin(message.from_user.id):
            bot.reply_to(
                message,
                bold_decor("⚙️ البوت في وضع الصيانة حاليًا\n\nسيتم إعادته للعمل قريبًا.\nنعتذر عن الإزعاج."),
                parse_mode="Markdown"
            )
            return
        
        allowed, reason = check_group_access(message)
        if allowed:
            return func(message, *args, **kwargs)
        else:
            access_denied_message(message, reason)
            return
    return wrapper

class FF_CLient:
    def __init__(self, id, password):
        self.id = id
        self.password = password
        self.key = None
        self.iv = None
        self.CliEnts = None
        self.CliEnts2 = None
        self.AutH_ToKen_0115 = None
        self.DeCode_CliEnt_Uid = None
        self.input_msg = ""
        self.Get_FiNal_ToKen_0115()
            
    def Connect_SerVer_OnLine(self, Token, tok, host, port, key, iv, host2, port2):
        try:
            self.AutH_ToKen_0115 = tok    
            self.CliEnts2 = socket.create_connection((host2, int(port2)))
            self.CliEnts2.send(bytes.fromhex(self.AutH_ToKen_0115))                  
        except:
            pass        
        while True:
            try:
                self.DaTa2 = self.CliEnts2.recv(99999)
                if '0500' in self.DaTa2.hex()[0:4] and len(self.DaTa2.hex()) > 30:
                    self.packet = json.loads(DeCode_PackEt(f'08{self.DaTa2.hex().split("08", 1)[1]}'))
                    self.AutH = self.packet['5']['data']['7']['data']
            except:
                pass
                                                            
    def Connect_SerVer(self, Token, tok, host, port, key, iv, host2, port2):
        self.AutH_ToKen_0115 = tok    
        self.CliEnts = socket.create_connection((host, int(port)))
        self.CliEnts.send(bytes.fromhex(self.AutH_ToKen_0115))  
        self.DaTa = self.CliEnts.recv(1024)
        
        threading.Thread(target=self.Connect_SerVer_OnLine, args=(Token, tok, host, port, key, iv, host2, port2)).start()
        self.Exemple = xMsGFixinG('12345678')
        
        self.key = key
        self.iv = iv
        
        with connected_clients_lock:
            connected_clients[self.id] = self
            print(f"✅ تم تسجيل الحساب {self.id} في القائمة العالمية، عدد الحسابات الآن: {len(connected_clients)}")
        
        while True:
            try:
                self.DaTa = self.CliEnts.recv(1024)
                self.process_messages()
            except Exception as e:
                print(f"⚠️ خطأ في Connect_SerVer: {e}")
                try:
                    self.CliEnts.close()
                    if hasattr(self, 'CliEnts2'):
                        self.CliEnts2.close()
                except:
                    pass
                self.Connect_SerVer(Token, tok, host, port, key, iv, ip2, port2)
    
    def process_messages(self):
        try:
            msg_hex = self.DaTa.hex()
        except:
            pass
                                    
    def GeT_Key_Iv(self, serialized_data):
        my_message = xKEys.MyMessage()
        my_message.ParseFromString(serialized_data)
        timestamp, key, iv = my_message.field21, my_message.field22, my_message.field23
        timestamp_obj = Timestamp()
        timestamp_obj.FromNanoseconds(timestamp)
        timestamp_seconds = timestamp_obj.seconds
        timestamp_nanos = timestamp_obj.nanos
        combined_timestamp = timestamp_seconds * 1_000_000_000 + timestamp_nanos
        return combined_timestamp, key, iv

    def Guest_GeneRaTe(self, uid, password):
        url = "https://100067.connect.garena.com/oauth/guest/token/grant"
        headers = {
            "Host": "100067.connect.garena.com",
            "User-Agent": "GarenaMSDK/4.0.19P4(G011A ;Android 9;en;US;)",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "close",
        }
        data = {
            "uid": f"{uid}",
            "password": f"{password}",
            "response_type": "token",
            "client_type": "2",
            "client_secret": "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
            "client_id": "100067",
        }
        try:
            response = requests.post(url, headers=headers, data=data).json()
            access_token, open_id = response['access_token'], response['open_id']
            time.sleep(0.2)
            print(f'🔑 تم تسجيل الدخول للحساب: {uid}')
            return self.ToKen_GeneRaTe(access_token, open_id)
        except Exception as e:
            print(f"⚠️ خطأ في Guest_GeneRaTe: {e}")
            time.sleep(10)
            return self.Guest_GeneRaTe(uid, password)
                                        
    def GeT_LoGin_PorTs(self, jwt_token, payload):
        url = 'https://clientbp.ggpolarbear.com/GetLoginData'
        headers = {
            'Expect': '100-continue',
            'Authorization': f'Bearer {jwt_token}',
            'X-Unity-Version': '2022.3.47f1',
            'X-GA': 'v1 1',
            'ReleaseVersion': 'OB53',
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'UnityPlayer/2022.3.47f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)',
            'Host': 'clientbp.ggpolarbear.com',
            'Connection': 'close',
            'Accept-Encoding': 'deflate, gzip',
        }
        try:
            response = requests.post(url, headers=headers, data=payload, verify=False)
            data = json.loads(DeCode_PackEt(response.content.hex()))
            address, address2 = data['32']['data'], data['14']['data']
            ip, ip2 = address[:len(address) - 6], address2[:len(address2) - 6]
            port, port2 = address[len(address) - 5:], address2[len(address2) - 5:]
            return ip, port, ip2, port2
        except requests.RequestException as e:
            print(f"⚠️ خطأ في GeT_LoGin_PorTs: {e}")
        return None, None, None, None
        
    def ToKen_GeneRaTe(self, access_token, open_id):
        url = "https://loginbp.ggpolarbear.com/MajorLogin"
        headers = {
            'X-Unity-Version': '2022.3.47f1',
            'ReleaseVersion': 'OB53',
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-GA': 'v1 1',
            'Content-Length': '928',
            'User-Agent': 'UnityPlayer/2022.3.47f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)',
            'Host': 'loginbp.ggpolarbear.com',
            'Connection': 'Keep-Alive',
            'Accept-Encoding': 'deflate, gzip',
        }
        
        dt = bytes.fromhex('1a13323032352d31312d32362030313a35313a3238220966726565206669726528013a07312e3132332e314232416e64726f6964204f532039202f204150492d3238202850492f72656c2e636a772e32303232303531382e313134313333294a0848616e6468656c64520c4d544e2f537061636574656c5a045749464960800a68d00572033234307a2d7838362d3634205353453320535345342e3120535345342e32204156582041565832207c2032343030207c20348001e61e8a010f416472656e6f2028544d292036343092010d4f70656e474c20455320332e329a012b476f6f676c657c36323566373136662d393161372d343935622d396631362d303866653964336336353333a2010e3137362e32382e3133392e313835aa01026172b201203433303632343537393364653836646134323561353263616164663231656564ba010134c2010848616e6468656c64ca010d4f6e65506c7573204135303130ea014063363961653230386661643732373338623637346232383437623530613361316466613235643161313966616537343566633736616334613065343134633934f00101ca020c4d544e2f537061636574656cd2020457494649ca03203161633462383065636630343738613434323033626638666163363132306635e003b5ee02e8039a8002f003af13f80384078004a78f028804b5ee029004a78f029804b5ee02b00404c80401d2043d2f646174612f6170702f636f6d2e6474732e667265656669726574682d66705843537068495636644b43376a4c2d574f7952413d3d2f6c69622f61726de00401ea045f65363261623933353464386662356662303831646233333861636233333439317c2f646174612f6170702f636f6d2e6474732e667265656669726574682d66705843537068495636644b43376a4c2d574f7952413d3d2f626173652e61706bf00406f804018a050233329a050a32303139313139303236a80503b205094f70656e474c455332b805ff01c00504e005be7eea05093372645f7061727479f205704b717348543857393347646347335a6f7a454e6646775648746d377171316552554e6149444e67526f626f7a4942744c4f695943633459367a767670634943787a514632734f453463627974774c7334785a62526e70524d706d5752514b6d654f35766373386e51594268777148374bf805e7e4068806019006019a060134a2060134b2062213521146500e590349510e460900115843395f005b510f685b560a6107576d0f0366')
        
        dt = dt.replace(b'2026-01-14 12:19:02', str(datetime.now())[:-7].encode())
        dt = dt.replace(b'c69ae208fad72738b674b2847b50a3a1dfa25d1a19fae745fc76ac4a0e414c94', access_token.encode())
        dt = dt.replace(b'4306245793de86da425a52caadf21eed', open_id.encode())
        
        try:
            hex_data = dt.hex()
            encoded_data = EnC_AEs(hex_data)
            payload = bytes.fromhex(encoded_data)
        except Exception as e:
            print(f"⚠️ خطأ في التشفير: {e}")
            payload = dt
        
        response = requests.post(url, headers=headers, data=payload, verify=False)
        
        if response.status_code == 200 and len(response.text) > 10:
            try:
                data = json.loads(DeCode_PackEt(response.content.hex()))
                jwt_token = data['8']['data']
                combined_timestamp, key, iv = self.GeT_Key_Iv(response.content)
                ip, port, ip2, port2 = self.GeT_LoGin_PorTs(jwt_token, payload)
                return jwt_token, key, iv, combined_timestamp, ip, port, ip2, port2
            except Exception as e:
                print(f"⚠️ خطأ في تحليل الاستجابة: {e}")
                time.sleep(5)
                return self.ToKen_GeneRaTe(access_token, open_id)
        else:
            print(f"⚠️ خطأ في ToKen_GeneRaTe, الحالة: {response.status_code}")
            time.sleep(5)
            return self.ToKen_GeneRaTe(access_token, open_id)
      
    def Get_FiNal_ToKen_0115(self):
        try:
            result = self.Guest_GeneRaTe(self.id, self.password)
            if not result:
                print("⚠️ فشل الحصول على التوكن، إعادة المحاولة...")
                time.sleep(5)
                return self.Get_FiNal_ToKen_0115()
                
            token, key, iv, timestamp, ip, port, ip2, port2 = result
            
            if not all([ip, port, ip2, port2]):
                print("⚠️ فشل الحصول على المنافذ، إعادة المحاولة...")
                time.sleep(5)
                return self.Get_FiNal_ToKen_0115()
                
            self.JwT_ToKen = token
        
            try:
                decoded = jwt.decode(token, options={"verify_signature": False})
                self.AccounT_Uid = decoded.get('account_id')
                self.EncoDed_AccounT = hex(self.AccounT_Uid)[2:]
                self.HeX_VaLue = DecodE_HeX(timestamp)
                self.TimE_HEx = self.HeX_VaLue
                self.JwT_ToKen_ = token.encode().hex()
                print(f'🔑 تم تسجيل الدخول: {self.AccounT_Uid}')
            except Exception as e:
                print(f"⚠️ خطأ في فك التوكن: {e}")
                time.sleep(5)
                return self.Get_FiNal_ToKen_0115()
                
            try:
                self.Header = hex(len(EnC_PacKeT(self.JwT_ToKen_, key, iv)) // 2)[2:]
                length = len(self.EncoDed_AccounT)
                self.zeros = '00000000'
                if length == 9:
                    self.zeros = '0000000'
                elif length == 8:
                    self.zeros = '00000000'
                elif length == 10:
                    self.zeros = '000000'
                elif length == 7:
                    self.zeros = '000000000'
                
                self.Header = f'0115{self.zeros}{self.EncoDed_AccounT}{self.TimE_HEx}00000{self.Header}'
                self.FiNal_ToKen_0115 = self.Header + EnC_PacKeT(self.JwT_ToKen_, key, iv)
            except Exception as e:
                print(f"⚠️ خطأ في إنشاء التوكن النهائي: {e}")
                time.sleep(5)
                return self.Get_FiNal_ToKen_0115()
                
            self.AutH_ToKen = self.FiNal_ToKen_0115
            self.Connect_SerVer(self.JwT_ToKen, self.AutH_ToKen, ip, port, key, iv, ip2, port2)
            return self.AutH_ToKen, key, iv
            
        except Exception as e:
            print(f"⚠️ خطأ عام في Get_FiNal_ToKen_0115: {e}")
            time.sleep(10)
            return self.Get_FiNal_ToKen_0115()

def start_account(account):
    try:
        print(f"🔄 بدء تشغيل الحساب: {account['id']}")
        FF_CLient(account['id'], account['password'])
    except Exception as e:
        print(f"⚠️ خطأ في تشغيل الحساب {account['id']}: {e}")
        time.sleep(5)
        start_account(account)

def start_all_accounts():
    threads = []
    for account in ACCOUNTS:
        thread = threading.Thread(target=start_account, args=(account,))
        thread.daemon = True
        threads.append(thread)
        thread.start()
        time.sleep(3)
    return threads

def send_spam_from_all_accounts(target_id):
    with connected_clients_lock:
        for account_id, client in connected_clients.items():
            try:
                if (hasattr(client, 'CliEnts2') and client.CliEnts2 and
                    hasattr(client, 'key') and client.key and
                    hasattr(client, 'iv') and client.iv):
                    
                    try:
                        client.CliEnts2.send(openroom(client.key, client.iv))
                        print(f"📂 فتح الغرفة من الحساب: {account_id}")
                    except Exception as e:
                        print(f"⚠️ خطأ في فتح الغرفة من {account_id}: {e}")
                    
                    for i in range(10):
                        try:
                            client.CliEnts2.send(spmroom(client.key, client.iv, target_id))
                            print(f"📨 سبام من {account_id} إلى {target_id} - المحاولة {i+1}")
                        except (BrokenPipeError, ConnectionResetError, OSError) as e:
                            print(f"⚠️ خطأ اتصال للحساب {account_id}: {e}")
                            break
                        except Exception as e:
                            print(f"⚠️ خطأ في الإرسال من {account_id}: {e}")
                            break
                else:
                    print(f"⚠️ اتصال الحساب {account_id} غير نشط")
            except Exception as e:
                print(f"⚠️ خطأ في إرسال السبام من {account_id}: {e}")

def spam_worker(target_id, duration_minutes=None, chat_id=None):
    print(f"🔥 بدء السبام على الهدف: {target_id}" + (f" لمدة {duration_minutes} دقيقة" if duration_minutes else ""))
    
    start_time = datetime.now()
    cycle_count = 0
    
    while True:
        with active_spam_lock:
            if target_id not in active_spam_targets:
                print(f"⏹️ توقف السبام على الهدف: {target_id}")
                break
                
            if duration_minutes:
                elapsed = datetime.now() - start_time
                if elapsed.total_seconds() >= duration_minutes * 60:
                    print(f"✅ انتهت مدة السبام على الهدف: {target_id}")
                    del active_spam_targets[target_id]
                    if chat_id:
                        try:
                            bot.send_message(
                                chat_id=chat_id,
                                text=bold_decor(f"✅ انتهى سبام {target_id}\n⏱️ المدة: {duration_minutes} دقيقة\n📊 إجمالي الدورات: {cycle_count}"),
                                parse_mode="Markdown"
                            )
                        except:
                            pass
                    break
        
        try:
            send_spam_from_all_accounts(target_id)
            cycle_count += 1
            
            if cycle_count % 10 == 0:
                print(f"📊 الدورة {cycle_count} اكتملت - {target_id}")
                    
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ خطأ في السبام على {target_id}: {e}")
            time.sleep(1)

def auto_restart_timer():
    while True:
        time.sleep(660)
        print("🔄 [AUTO-RESTART] جاري إعادة تشغيل البوت تلقائياً بعد 11 دقيقة...")
        
        try:
            for admin_id in ADMIN_IDS:
                try:
                    bot.send_message(
                        admin_id,
                        bold_decor("🔄 إعادة تشغيل تلقائي\n\nسيتم إعادة تشغيل البوت تلقائياً بعد 1 ساعة من التشغيل.\nجاري إعادة التشغيل الآن..."),
                        parse_mode="Markdown"
                    )
                except:
                    pass
        except:
            pass
        
        time.sleep(2)
        
        python = sys.executable
        os.execl(python, python, *sys.argv)

# ========== الأزرار ==========
def main_menu_buttons():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🚀 سبام", callback_data="menu_spam"),
        InlineKeyboardButton("⏹️ إيقاف", callback_data="menu_stop"),
        InlineKeyboardButton("📊 الحالة", callback_data="menu_status"),
        InlineKeyboardButton("📋 الحسابات", callback_data="menu_accounts"),
        InlineKeyboardButton("❓ مساعدة", callback_data="menu_help")
    )
    return kb

def admin_panel_buttons():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("➕ تفعيل 30 يوم", callback_data="admin_activate_30"),
        InlineKeyboardButton("➖ إلغاء تفعيل", callback_data="admin_deactivate"),
        InlineKeyboardButton("📋 المجموعات", callback_data="admin_groups"),
        InlineKeyboardButton("🛠️ صيانة ON", callback_data="admin_maint_on"),
        InlineKeyboardButton("🟢 صيانة OFF", callback_data="admin_maint_off"),
        InlineKeyboardButton("⏹️ إيقاف الكل", callback_data="admin_stopall"),
        InlineKeyboardButton("🔄 إعادة تشغيل", callback_data="admin_restart"),
        InlineKeyboardButton("📢 إذاعة", callback_data="admin_broadcast"),
        InlineKeyboardButton("🔑 إعادة تسجيل", callback_data="admin_login")
    )
    return kb

# ========== أوامر البوت بالأزرار ==========
@bot.message_handler(commands=['start'])
def start_command(message):
    if maintenance_mode and not is_admin(message.from_user.id):
        bot.reply_to(message, bold_decor("⚙️ البوت في وضع الصيانة حاليًا\n\nسيتم إعادته للعمل قريبًا.\nنعتذر عن الإزعاج."), parse_mode="Markdown")
        return
    
    if is_private_chat(message):
        if is_admin(message.from_user.id):
            with connected_clients_lock:
                accounts_count = len(connected_clients)
            bot.send_message(message.chat.id, fancy_text(f"مرحباً مطور 🧠 | حسابات: {accounts_count}/{len(ACCOUNTS)}"), reply_markup=admin_panel_buttons(), parse_mode="Markdown")
        else:
            bot.reply_to(message, "🗿")
        return
    
    if is_group_activated(message.chat.id):
        bot.send_message(message.chat.id, bold_decor(f"🔥 *ISMAIL SPAM نشط*\nاستخدم الأزرار بالأسفل"), reply_markup=main_menu_buttons(), parse_mode="Markdown")
    else:
        access_denied_message(message, "group_not_activated")

@bot.message_handler(commands=['help'])
def help_command(message):
    if is_private_chat(message) and is_admin(message.from_user.id):
        bot.send_message(message.chat.id, fancy_text("لوحة تحكم المطور"), reply_markup=admin_panel_buttons(), parse_mode="Markdown")
    elif not is_private_chat(message) and is_group_activated(message.chat.id):
        bot.send_message(message.chat.id, fancy_text("القائمة الرئيسية"), reply_markup=main_menu_buttons(), parse_mode="Markdown")
    else:
        if is_private_chat(message) and not is_admin(message.from_user.id):
            bot.reply_to(message, "🗿")
        else:
            help_text = bold_decor("🛡️ *الأوامر المتاحة*\n/spam id [مدة]\n/stop id\n/status\n/accounts\n/id\n━━━━━━\nللمطور: /activate, /deactivate, /groups, /maintenance, /unmaintenance, /stopall, /restart, /broadcast, /login")
            bot.reply_to(message, help_text, parse_mode="Markdown")

# ========== أمر الآيدي المضاف جديداً ==========
@bot.message_handler(commands=['id'])
def get_my_id(message):
    # لا نقوم بوضع الفلتر هنا لكي يتمكن أي شخص من معرفة آيديه والجروب حتى لو كان غير مفعل
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if message.chat.type == "private":
        text = f"👤 *الآيدي الخاص بك:* `{user_id}`"
    else:
        text = f"👤 *الآيدي الخاص بك:* `{user_id}`\n👥 *آيدي المجموعة:* `{chat_id}`"
        
    bot.reply_to(message, bold_decor(text), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    msg = call.message
    
    if call.data == "menu_spam":
        bot.edit_message_text(bold_decor("🎯 *أرسل الأمر:* `/spam [id] [مدة]`"), chat_id, msg.message_id, parse_mode="Markdown")
    elif call.data == "menu_stop":
        bot.edit_message_text(bold_decor("⏹️ *أرسل:* `/stop [id]`"), chat_id, msg.message_id, parse_mode="Markdown")
    elif call.data == "menu_status":
        with active_spam_lock: targets = len(active_spam_targets)
        with connected_clients_lock: acc = len(connected_clients)
        status = bold_decor(f"📊 *الحالة*\n✅ حسابات: {acc}/{len(ACCOUNTS)}\n🎯 هجمات: {targets}\n📌 مجموعات: {len(ACTIVATED_GROUPS)}")
        bot.edit_message_text(status, chat_id, msg.message_id, parse_mode="Markdown")
    elif call.data == "menu_accounts":
        with connected_clients_lock: lst = list(connected_clients.keys())
        txt = "📋 *الحسابات المتصلة:*\n" + "\n".join([f"• `{a}`" for a in lst[:15]]) + (f"\n... و{len(lst)-15} أخرى" if len(lst)>15 else "")
        bot.edit_message_text(bold_decor(txt), chat_id, msg.message_id, parse_mode="Markdown")
    elif call.data == "menu_help":
        help_txt = bold_decor("🛡️ *الأوامر المتاحة*\n/spam id [مدة]\n/stop id\n/status\n/accounts\n/id\n━━━━━━\nللمطور: /activate, /deactivate, /groups, /maintenance, /unmaintenance, /stopall, /restart, /broadcast, /login")
        bot.edit_message_text(help_txt, chat_id, msg.message_id, parse_mode="Markdown")
    
    elif is_admin(user_id):
        if call.data == "admin_activate_30":
            if chat_id < 0:
                expiry = time.time() + 30*86400
                ACTIVATED_GROUPS[str(chat_id)] = expiry
                save_activated_groups()
                bot.edit_message_text(bold_decor(f"✅ *تم التفعيل 30 يومًا* لـ `{chat_id}`"), chat_id, msg.message_id, parse_mode="Markdown")
            else:
                bot.edit_message_text(bold_decor("❌ استخدم هذا الزر في مجموعة"), chat_id, msg.message_id, parse_mode="Markdown")
        elif call.data == "admin_deactivate":
            if str(chat_id) in ACTIVATED_GROUPS:
                del ACTIVATED_GROUPS[str(chat_id)]
                save_activated_groups()
                bot.edit_message_text(bold_decor(f"✅ *تم إلغاء التفعيل* `{chat_id}`"), chat_id, msg.message_id, parse_mode="Markdown")
            else:
                bot.edit_message_text(bold_decor("⚠️ غير مفعلة"), chat_id, msg.message_id, parse_mode="Markdown")
        elif call.data == "admin_groups":
            if ACTIVATED_GROUPS:
                txt = "📋 *المجموعات المفعلة:*\n" + "\n".join([f"• `{gid}` → {format_remaining_time(exp)}" for gid,exp in list(ACTIVATED_GROUPS.items())[:10]])
            else:
                txt = "📭 لا توجد مجموعات"
            bot.edit_message_text(bold_decor(txt), chat_id, msg.message_id, parse_mode="Markdown")
        elif call.data == "admin_maint_on":
            save_maintenance_status(True)
            bot.edit_message_text(bold_decor("⚙️ *وضع الصيانة مُفعل*"), chat_id, msg.message_id, parse_mode="Markdown")
        elif call.data == "admin_maint_off":
            save_maintenance_status(False)
            bot.edit_message_text(bold_decor("🟢 *وضع الصيانة معطل*"), chat_id, msg.message_id, parse_mode="Markdown")
        elif call.data == "admin_stopall":
            with active_spam_lock: active_spam_targets.clear()
            bot.edit_message_text(bold_decor("✅ *تم إيقاف جميع الهجمات*"), chat_id, msg.message_id, parse_mode="Markdown")
        elif call.data == "admin_restart":
            bot.edit_message_text(bold_decor("🔄 *جاري إعادة التشغيل...*"), chat_id, msg.message_id, parse_mode="Markdown")
            time.sleep(1)
            os.execl(sys.executable, sys.executable, *sys.argv)
        elif call.data == "admin_broadcast":
            bot.edit_message_text(bold_decor("📢 *أرسل رسالة الإذاعة الآن*\nاكتب: /broadcast نص الرسالة"), chat_id, msg.message_id, parse_mode="Markdown")
        elif call.data == "admin_login":
            bot.edit_message_text(bold_decor("🔑 *جاري إعادة تسجيل الحسابات...*"), chat_id, msg.message_id, parse_mode="Markdown")
            threading.Thread(target=start_all_accounts).start()
    
    else:
        bot.answer_callback_query(call.id, "⛔ هذا الزر للمطور فقط", show_alert=True)
    
    bot.answer_callback_query(call.id)

# ========== أوامر السبام والستوب والستاتس والأكونتات ==========
@bot.message_handler(commands=['spam', 'stop', 'status', 'accounts'])
def handle_user_commands(message):
    if is_private_chat(message):
        if is_admin(message.from_user.id):
            if message.text.startswith('/status') or message.text.startswith('/accounts'):
                if message.text.startswith('/status'):
                    status_command(message)
                elif message.text.startswith('/accounts'):
                    accounts_command(message)
            else:
                bot.reply_to(message, "❌ هذا الأمر لا يعمل في المحادثات الخاصة\nيرجى استخدامه في المجموعات فقط")
        else:
            bot.reply_to(message, "🗿")
        return
    
    if message.text.startswith('/spam'):
        spam_command(message)
    elif message.text.startswith('/stop'):
        stop_command(message)
    elif message.text.startswith('/status'):
        status_command(message)
    elif message.text.startswith('/accounts'):
        accounts_command(message)

def spam_command(message):
    if maintenance_mode and not is_admin(message.from_user.id):
        bot.reply_to(message, bold_decor("⚙️ البوت في وضع الصيانة حاليًا\n\nسيتم إعادته للعمل قريبًا.\nنعتذر عن الإزعاج."), parse_mode="Markdown")
        return
    
    allowed, reason = check_group_access(message)
    if not allowed:
        access_denied_message(message, reason)
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, bold_decor("❌ استخدم: `/spam [الهدف] [الدقائق]`"), parse_mode="Markdown")
        return
    
    target_id = parts[1]
    duration = int(parts[2]) if len(parts) > 2 else None
    
    try:
        if not ChEck_Commande(target_id):
            bot.reply_to(message, bold_decor("❌ user_id غير صالح!"), parse_mode="Markdown")
            return
    except:
        pass
    
    with active_spam_lock:
        if target_id in active_spam_targets:
            elapsed = datetime.now() - active_spam_targets[target_id]['start_time']
            minutes = int(elapsed.total_seconds() / 60)
            bot.reply_to(message, bold_decor(f"⚠️ سبام نشط على {target_id} منذ {minutes} دقيقة"), parse_mode="Markdown")
            return
        
        active_spam_targets[target_id] = {
            'active': True,
            'start_time': datetime.now(),
            'duration': duration,
            'user_id': user_id,
            'chat_id': chat_id
        }
    
    duration_text = f" لمدة {duration} دقيقة" if duration else " بشكل مستمر"
    bot.reply_to(message, bold_decor(f"🚀 بدأ السبام على {target_id}{duration_text}\nلإيقاف: /stop {target_id}"), parse_mode="Markdown")
    
    def run_spam():
        spam_worker(target_id, duration, chat_id)
        with active_spam_lock:
            if target_id in active_spam_targets:
                del active_spam_targets[target_id]
    
    thread = threading.Thread(target=run_spam, daemon=True)
    thread.start()

def stop_command(message):
    if maintenance_mode and not is_admin(message.from_user.id):
        bot.reply_to(message, bold_decor("⚙️ البوت في وضع الصيانة حاليًا\n\nسيتم إعادته للعمل قريبًا.\nنعتذر عن الإزعاج."), parse_mode="Markdown")
        return
    
    allowed, reason = check_group_access(message)
    if not allowed:
        access_denied_message(message, reason)
        return
    
    user_id = message.from_user.id
    parts = message.text.split()
    
    if len(parts) < 2:
        bot.reply_to(message, bold_decor("❌ استخدم: /stop [الهدف]"), parse_mode="Markdown")
        return
    
    target_id = parts[1]
    
    with active_spam_lock:
        if target_id in active_spam_targets:
            if active_spam_targets[target_id]['user_id'] == user_id or is_admin(user_id):
                active_spam_targets[target_id]['active'] = False
                time.sleep(0.5)
                if target_id in active_spam_targets:
                    del active_spam_targets[target_id]
                bot.reply_to(message, bold_decor(f"⏹️ تم إيقاف السبام على {target_id}"), parse_mode="Markdown")
            else:
                bot.reply_to(message, bold_decor("❌ هذا الهجوم ليس لك"), parse_mode="Markdown")
        else:
            bot.reply_to(message, bold_decor(f"❌ لا يوجد سبام نشط على {target_id}"), parse_mode="Markdown")

def status_command(message):
    if maintenance_mode and not is_admin(message.from_user.id):
        bot.reply_to(message, bold_decor("⚙️ البوت في وضع الصيانة حاليًا\n\nسيتم إعادته للعمل قريبًا.\nنعتذر عن الإزعاج."), parse_mode="Markdown")
        return
    
    if not is_admin(message.from_user.id):
        allowed, reason = check_group_access(message)
        if not allowed:
            access_denied_message(message, reason)
            return
    
    with active_spam_lock:
        targets = list(active_spam_targets.keys())
    
    with connected_clients_lock:
        accounts_count = len(connected_clients)
    
    chat_id = message.chat.id
    group_status = "✅ مفعلة"
    remaining = ""
    
    if str(chat_id) in ACTIVATED_GROUPS:
        expiry = ACTIVATED_GROUPS[str(chat_id)]
        if expiry > time.time():
            remaining = f"\n⏳ متبقي: {format_remaining_time(expiry)}"
        else:
            group_status = "❌ منتهية الصلاحية"
    
    status_text = bold_decor(f"📊 *حالة النظام*\n\n📌 المجموعة: {group_status}{remaining}\n✅ الحسابات المتصلة: {accounts_count}/{len(ACCOUNTS)}\n🎯 الهجمات النشطة: {len(targets)}")
    
    if targets:
        status_text += "\n\nالأهداف:\n" + "\n".join([f"• {tid}" for tid in targets[:5]])
        if len(targets) > 5:
            status_text += f"\n• ... و {len(targets) - 5} هدف آخر"
    
    bot.reply_to(message, status_text, parse_mode="Markdown")

def accounts_command(message):
    if maintenance_mode and not is_admin(message.from_user.id):
        bot.reply_to(message, bold_decor("⚙️ البوت في وضع الصيانة حاليًا\n\nسيتم إعادته للعمل قريبًا.\nنعتذر عن الإزعاج."), parse_mode="Markdown")
        return
    
    if not is_admin(message.from_user.id):
        allowed, reason = check_group_access(message)
        if not allowed:
            access_denied_message(message, reason)
            return
    
    with connected_clients_lock:
        accounts_count = len(connected_clients)
        accounts_list = list(connected_clients.keys())
    
    if not accounts_list:
        bot.reply_to(message, bold_decor(f"📭 لا توجد حسابات متصلة\n✅ الإجمالي: {len(ACCOUNTS)}"), parse_mode="Markdown")
        return
    
    text = f"📋 *الحسابات المتصلة:* {accounts_count}/{len(ACCOUNTS)}\n\n"
    
    for acc in accounts_list[:10]:
        text += f"• `{acc}`\n"
    
    if len(accounts_list) > 10:
        text += f"• ... و {len(accounts_list) - 10} حساب آخر"
    
    bot.reply_to(message, bold_decor(text), parse_mode="Markdown")

# ========== أوامر المسؤول ==========
@bot.message_handler(commands=['activate', 'deactivate', 'groups', 'maintenance', 'unmaintenance', 'stopall', 'restart', 'broadcast', 'login'])
def handle_admin_commands(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, bold_decor("⛔ هذا الأمر للمسؤولين فقط"), parse_mode="Markdown")
        return
    
    if message.text.startswith('/activate'):
        activate_group_command(message)
    elif message.text.startswith('/deactivate'):
        deactivate_group_command(message)
    elif message.text.startswith('/groups'):
        groups_command(message)
    elif message.text.startswith('/maintenance'):
        maintenance_on_command(message)
    elif message.text.startswith('/unmaintenance'):
        maintenance_off_command(message)
    elif message.text.startswith('/stopall'):
        stopall_command(message)
    elif message.text.startswith('/restart'):
        restart_command(message)
    elif message.text.startswith('/broadcast'):
        broadcast_command(message)
    elif message.text.startswith('/login'):
        login_command(message)

def activate_group_command(message):
    if message.chat.type == 'private':
        bot.reply_to(message, bold_decor("❌ يجب استخدام هذا الأمر في المجموعة المراد تفعيلها"), parse_mode="Markdown")
        return
    
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, bold_decor("❌ استخدم: /activate [عدد الأيام]"), parse_mode="Markdown")
        return
    
    try:
        days = int(parts[1])
        if days <= 0:
            bot.reply_to(message, bold_decor("❌ عدد الأيام يجب أن يكون أكبر من 0"), parse_mode="Markdown")
            return
        
        chat_id = str(message.chat.id)
        expiry_time = time.time() + (days * 86400)
        
        ACTIVATED_GROUPS[chat_id] = expiry_time
        save_activated_groups()
        
        expiry_date = datetime.fromtimestamp(expiry_time).strftime("%Y-%m-%d %H:%M:%S")
        
        bot.reply_to(message, bold_decor(f"✅ تم تفعيل المجموعة بنجاح\n\n📌 المدة: {days} يوم\n⏳ تنتهي في: {expiry_date}\n🆔 معرف المجموعة: {chat_id}"), parse_mode="Markdown")
        
    except ValueError:
        bot.reply_to(message, bold_decor("❌ عدد الأيام يجب أن يكون رقماً صحيحاً"), parse_mode="Markdown")

def deactivate_group_command(message):
    if message.chat.type == 'private':
        bot.reply_to(message, bold_decor("❌ يجب استخدام هذا الأمر في المجموعة المراد إلغاء تفعيلها"), parse_mode="Markdown")
        return
    
    chat_id = str(message.chat.id)
    
    if chat_id in ACTIVATED_GROUPS:
        del ACTIVATED_GROUPS[chat_id]
        save_activated_groups()
        bot.reply_to(message, bold_decor(f"✅ تم إلغاء تفعيل المجموعة {chat_id}"), parse_mode="Markdown")
    else:
        bot.reply_to(message, bold_decor("⚠️ هذه المجموعة غير مفعلة أصلاً"), parse_mode="Markdown")

def groups_command(message):
    if not ACTIVATED_GROUPS:
        bot.reply_to(message, bold_decor("📭 لا توجد مجموعات مفعلة حالياً"), parse_mode="Markdown")
        return
    
    text = f"📋 *المجموعات المفعلة:* {len(ACTIVATED_GROUPS)}\n\n"
    
    for i, (group_id, expiry) in enumerate(list(ACTIVATED_GROUPS.items())[:10], 1):
        remaining = format_remaining_time(expiry)
        text += f"{i}. `{group_id}`\n   ⏳ {remaining}\n\n"
    
    if len(ACTIVATED_GROUPS) > 10:
        text += f"\n... و {len(ACTIVATED_GROUPS) - 10} مجموعة أخرى"
    
    bot.reply_to(message, bold_decor(text), parse_mode="Markdown")

def maintenance_on_command(message):
    if maintenance_mode:
        bot.reply_to(message, bold_decor("⚠️ وضع الصيانة مفعل بالفعل"), parse_mode="Markdown")
        return
    
    save_maintenance_status(True)
    
    maintenance_msg = bold_decor("⚙️ تنبيه: وضع الصيانة ⚙️\n\nتم تفعيل وضع الصيانة.\nلن يتمكن المستخدمون من استخدام البوت حتى إشعار آخر.\n\nسيتم إعلامكم عند الانتهاء.")
    
    bot.reply_to(message, bold_decor("✅ تم تفعيل وضع الصيانة"), parse_mode="Markdown")
    
    threading.Thread(target=send_message_to_all_groups, args=(maintenance_msg,)).start()

def maintenance_off_command(message):
    if not maintenance_mode:
        bot.reply_to(message, bold_decor("⚠️ وضع الصيانة غير مفعل أصلاً"), parse_mode="Markdown")
        return
    
    save_maintenance_status(False)
    
    unmaintenance_msg = bold_decor("🎉 إشعار هام 🎉\n\nتم إيقاف وضع الصيانة.\nالبوت يعمل الآن بشكل طبيعي.\n\nشكراً لصبركم ❤️")
    
    bot.reply_to(message, bold_decor("✅ تم إيقاف وضع الصيانة"), parse_mode="Markdown")
    
    threading.Thread(target=send_message_to_all_groups, args=(unmaintenance_msg,)).start()

def stopall_command(message):
    with active_spam_lock:
        targets_count = len(active_spam_targets)
        active_spam_targets.clear()
    
    bot.reply_to(message, bold_decor(f"✅ تم إيقاف جميع الهجمات ({targets_count} هدف)"), parse_mode="Markdown")

def restart_command(message):
    bot.reply_to(message, bold_decor("🔄 جاري إعادة تشغيل البوت..."), parse_mode="Markdown")
    time.sleep(2)
    python = sys.executable
    os.execl(python, python, *sys.argv)

def broadcast_command(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, bold_decor("❌ استخدم: /broadcast [الرسالة]"), parse_mode="Markdown")
        return
    
    broadcast_msg = parts[1]
    formatted_msg = bold_decor(f"📢 إشعار من الإدارة 📢\n\n{broadcast_msg}")
    
    msg = bot.reply_to(message, bold_decor(f"🔄 جاري إرسال الرسالة إلى {len(ACTIVATED_GROUPS)} مجموعة..."), parse_mode="Markdown")
    
    success = 0
    failed = 0
    
    for group_id in list(ACTIVATED_GROUPS.keys()):
        try:
            bot.send_message(group_id, formatted_msg, parse_mode="Markdown")
            success += 1
            time.sleep(1)
        except Exception as e:
            print(f"⚠️ فشل إرسال إلى {group_id}: {e}")
            failed += 1
    
    bot.edit_message_text(bold_decor(f"✅ تم الإرسال\n✓ نجح: {success}\n✗ فشل: {failed}"), msg.chat.id, msg.message_id, parse_mode="Markdown")

def login_command(message):
    msg = bot.reply_to(message, bold_decor("🔄 جاري تسجيل دخول الحسابات..."), parse_mode="Markdown")
    
    def run_login():
        start_all_accounts()
        try:
            bot.edit_message_text(bold_decor(f"✅ تم بدء تسجيل دخول {len(ACCOUNTS)} حساب"), msg.chat.id, msg.message_id, parse_mode="Markdown")
        except:
            pass
    
    thread = threading.Thread(target=run_login, daemon=True)
    thread.start()

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    if is_private_chat(message):
        if is_admin(message.from_user.id):
            bot.reply_to(message, fancy_text("مرحباً أيها المطور\nاستخدم /help لعرض أوامر المسؤول المتاحة"), parse_mode="Markdown")
        else:
            bot.reply_to(message, "🗿")
        return
    
    if maintenance_mode and not is_admin(message.from_user.id):
        return
    
    allowed, reason = check_group_access(message)
    if not allowed:
        if reason == "group_not_activated":
            access_denied_message(message, reason)
        return

# ========== تشغيل البوت ==========
restart_thread = threading.Thread(target=auto_restart_timer, daemon=True)
restart_thread.start()
print("✅ [AUTO-RESTART] تم تفعيل إعادة التشغيل التلقائي كل 11 دقيقة")

def run_bot():
    try:
        print("✅ بدء تشغيل البوت...")
        bot.infinity_polling()
    except Exception as e:
        print(f"❌ خطأ في البوت: {e}")
        time.sleep(5)

expiry_check_thread = threading.Thread(target=check_expired_groups, daemon=True)
expiry_check_thread.start()

bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()
print("✅ تم تشغيل البوت في الخلفية")

def main():
    print("═" * 60)
    print("🔥 ISMAIL SPAM BOT - الإصدار النهائي 🔥")
    print("═" * 60)
    print(f"✅ توكن البوت: {BOT_TOKEN[:15]}...")
    print(f"✅ المسؤولون: {len(ADMIN_IDS)} مسؤول")
    print(f"✅ عدد الحسابات: {len(ACCOUNTS)}")
    print(f"✅ المجموعات المفعلة: {len(ACTIVATED_GROUPS)}")
    print(f"✅ وضع الصيانة: {'مفعل' if maintenance_mode else 'غير مفعل'}")
    print(f"✅ إعادة التشغيل التلقائي: كل 1 ساعة")
    print("═" * 60)
    
    if ACTIVATED_GROUPS:
        print("📋 المجموعات المفعلة:")
        for i, (group_id, expiry) in enumerate(list(ACTIVATED_GROUPS.items())[:5], 1):
            remaining = format_remaining_time(expiry)
            print(f"   {i}. {group_id} - {remaining}")
        if len(ACTIVATED_GROUPS) > 5:
            print(f"   ... و {len(ACTIVATED_GROUPS) - 5} مجموعة أخرى")
    else:
        print("📭 لا توجد مجموعات مفعلة حالياً")
    print("═" * 60)
    
    print("🔄 جاري تسجيل دخول الحسابات...")
    account_threads = start_all_accounts()
    
    print("✅ البوت يعمل في الخلفية...")
    print("📱 أضف البوت إلى مجموعتك واستخدم /activate لتفعيلها")
    print("═" * 60)
    
    try:
        while True:
            time.sleep(60)
            with connected_clients_lock:
                conn_count = len(connected_clients)
            with active_spam_lock:
                active_count = len(active_spam_targets)
            print(f"📊 إحصاءات: {conn_count}/{len(ACCOUNTS)} حسابات متصلة | {active_count} هجوم نشط | {len(ACTIVATED_GROUPS)} مجموعة مفعلة")
    except KeyboardInterrupt:
        print("\n⏹️ تم إيقاف البوت")

if __name__ == "__main__":
    main()
