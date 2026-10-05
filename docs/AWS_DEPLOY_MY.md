# AWS ပေါ်တင်နည်း — မြန်မာလမ်းညွှန် (၁၃ ဆင့်)

ဒီစာရွက်က Dubbing Studio (မြန်မာ ⇄ အင်္ဂလိပ် အသံထပ်ရေးတဲ့ app) ကို AWS ပေါ်မှာ
ကိုယ်တိုင်တင်နိုင်အောင် အဆင့်ဆင့် ရှင်းပြထားတာပါ။ Linux မကျွမ်းကျင်သူလည်း
လိုက်လုပ်လို့ရအောင် command တစ်ကြောင်းချင်းစီ ရေးပေးထားပါတယ်။

**အချိန်** — ၂၀ မိနစ်ခန့် (အများစုက စောင့်ရတာ)
**ကုန်ကျစရိတ်** — တစ်လ ခန့်မှန်း US$15–20 (t3.small + EBS 30GB + S3 အနည်းငယ်)
**လိုအပ်ချက်** — AWS account တစ်ခု၊ credit card တစ်ခု၊ GitHub repo URL

> အကြံပြုချက် — ပထမဆုံးအကြိမ်မှာ **mock mode** နဲ့ပဲ စမ်းပါ။ AI မခေါ်တဲ့အတွက်
> ပိုက်ဆံမကုန်ဘဲ UI တစ်ခုလုံး အလုပ်လုပ်တာ မြင်ရပါမယ်။ အဆင်ပြေမှ provider တစ်ခုချင်း
> ဖွင့်ပါ။

---

## ပြင်ဆင်မှု — repo URL ရယူခြင်း

GitHub မှာ ဒီ project ကို push ထားပြီးသား ဖြစ်ရပါမယ်။ repo URL က ဒီလိုပုံစံ —

```
https://github.com/<သင့်အမည်>/<repo-အမည်>.git
```

Private repo ဆိုရင် server က clone လုပ်လို့မရပါဘူး။ ဖြေရှင်းနည်း နှစ်မျိုး —
repo ကို public ထားပါ၊ ဒါမှမဟုတ် GitHub personal access token ပါတဲ့ URL
(`https://<token>@github.com/...`) ကို သုံးပါ။

---

## အဆင့် ၁ — AWS CloudShell ဖွင့်ပါ

၁. <https://console.aws.amazon.com> ကို ဝင်ပါ။
၂. ညာဘက်အပေါ်ထောင့်မှာ region ကို **Asia Pacific (Singapore) ap-southeast-1**
   လို့ ရွေးပါ (မြန်မာနဲ့ အနီးဆုံး၊ ping နိမ့်ပါတယ်)။
၃. အပေါ်ဘားမှာရှိတဲ့ `>_` icon (CloudShell) ကို နှိပ်ပါ။
၄. အောက်မှာ black terminal တစ်ခု ပေါ်လာပါလိမ့်မယ်။ ၃၀ စက္ကန့်လောက် စောင့်ပါ။

CloudShell က AWS ထဲမှာပဲ run တဲ့ Linux terminal ဖြစ်လို့ သင့်ကွန်ပျူတာမှာ
ဘာမှ install စရာမလိုပါဘူး။ login credential လည်း အလိုအလျောက် ပါပြီးသားပါ။

## အဆင့် ၂ — code ကို CloudShell ထဲ ဆွဲချပါ

```bash
git clone https://github.com/<သင့်အမည်>/<repo-အမည်>.git dub
cd dub
```

## အဆင့် ၃ — script ကို run ပါ

```bash
bash deploy/aws-deploy.sh
```

ဒါပဲ။ script က အောက်ပါအရာတွေကို အလိုအလျောက် ဆောက်ပေးပါတယ် —

| ဆောက်ပေးတာ | ဘာအတွက်လဲ |
|---|---|
| S3 bucket | ဗီဒီယို/အသံ သိမ်းဖို့ |
| Lifecycle rule | ရက် ၃၀ ကျော် file တွေ အလိုအလျောက် ဖျက် → ဈေးသက်သာ |
| CORS | browser ကနေ S3 ကို တိုက်ရိုက် upload တင်နိုင်ဖို့ |
| Secrets Manager | Gemini API key ကို လုံခြုံစွာ သိမ်းဖို့ |
| IAM role | server က bucket နဲ့ secret ကိုပဲ ဖတ်နိုင်ဖို့ (တခြားဘာမှ မရ) |
| Security group | SSH က သင့် IP ကပဲ၊ web port 80 က အားလုံး |
| EC2 instance | Ubuntu + Docker + API + worker + nginx |

script ထဲမှာ `[1/13] ... [13/13]` ဆိုပြီး အဆင့်တွေ ပြနေပါလိမ့်မယ်။

## အဆင့် ၄ — region ဒါမှမဟုတ် instance အရွယ် ပြောင်းချင်ရင်

default မလိုချင်ရင် run မလုပ်ခင် ဒီလို သတ်မှတ်ပါ —

```bash
export REGION=ap-southeast-1          # Singapore
export INSTANCE_TYPE=t3.small         # စမ်းဖို့ t3.micro လည်းရ
export VOLUME_GB=30
bash deploy/aws-deploy.sh
```

ရုပ်ရှင်အရှည်ကြီး လုပ်မယ်ဆိုရင် `t3.medium` (4GB RAM) က ပိုအဆင်ပြေပါတယ်။

## အဆင့် ၅ — ဆောက်နေတာကို စောင့်ပါ

`[12/13] Waiting for the instance to come up` မှာ ၅–၁၀ မိနစ် စောင့်ရပါမယ်။
Docker image build လုပ်တာနဲ့ frontend npm build လုပ်တာကြောင့်ပါ။
`ok  API is answering` တက်လာရင် ပြီးပါပြီ။

## အဆင့် ၆ — app ကို ဖွင့်ကြည့်ပါ

script အဆုံးမှာ ဒီလိုပြပါလိမ့်မယ် —

```
Open            http://13.250.xx.xx
Access token    9f3c2a...
```

browser မှာ အဲဒီ IP ကို ဖွင့်ပါ။ Settings စာမျက်နှာမှာ token ကို ထည့်ပြီး
သိမ်းလိုက်ပါ (browser ထဲမှာပဲ သိမ်းတာ၊ server ကို key မပို့ပါ)။

## အဆင့် ၇ — mock mode နဲ့ စမ်းပါ

၁. **New project** နှိပ်ပါ။
၂. ဗီဒီယိုတစ်ခု တင်ပါ (အတိုလေး ၃၀ စက္ကန့်လောက်နဲ့ စမ်းပါ)။
၃. **Run pipeline** နှိပ်ပါ။
၄. Editor မှာ စာကြောင်းတွေ၊ အချိန်တွေ ပြင်ကြည့်ပါ။
၅. Export tab မှာ MP4 / WAV / MP3 / SRT / VTT ဒေါင်းကြည့်ပါ။

အားလုံးက mock ဖြစ်လို့ အသံက အစစ်မဟုတ်ပါဘူး၊ ဒါပေမဲ့ လမ်းကြောင်းတစ်ခုလုံး
အလုပ်လုပ်မလုပ် စစ်လို့ရပါပြီ။ ဒီအဆင့်မှာ AI ကုန်ကျစရိတ် သုညပါ။

## အဆင့် ၈ — Gemini API key ထည့်ပါ

key ကို <https://aistudio.google.com/apikey> မှာ အခမဲ့ ယူနိုင်ပါတယ်။
CloudShell မှာ —

```bash
aws secretsmanager put-secret-value --region ap-southeast-1 \
  --secret-id dub-studio/gemini \
  --secret-string '{"GEMINI_API_KEY":"သင့်key"}'
```

key ဟာ server ဘက်မှာပဲ ရှိပါတယ်။ browser ဆီ ဘယ်တော့မှ မရောက်ပါဘူး။

## အဆင့် ၉ — server ထဲ SSH ဝင်ပါ

```bash
ssh -i ~/dub-studio-key.pem ubuntu@<သင့်IP>
```

CloudShell က key file ကို `~/dub-studio-key.pem` မှာ သိမ်းထားပါတယ်။
ကိုယ့်စက်ထဲ ယူချင်ရင် CloudShell menu → **Actions → Download file** ကနေ
ဒေါင်းပါ။ ပြီးရင် `chmod 400 dub-studio-key.pem` လုပ်ဖို့ မမေ့ပါနဲ့။

## အဆင့် ၁၀ — provider တစ်ခုချင်း ဖွင့်ပါ

server ထဲမှာ —

```bash
cd /opt/dub
sudo nano backend/.env
```

အစီအစဉ်အတိုင်း တစ်ခုချင်း ပြောင်းပါ (တစ်ခါတည်း အားလုံး မပြောင်းပါနဲ့) —

```ini
DUB_PROVIDER_RENDER=ffmpeg              # ၁။ ဗီဒီယိုအစစ် ထုတ်
DUB_PROVIDER_TRANSCRIPTION=faster_whisper   # ၂။ စကားကို စာအဖြစ် ပြောင်း
DUB_PROVIDER_TRANSLATION=gemini         # ၃။ ဘာသာပြန်
DUB_PROVIDER_TTS_MY=mms_tts             # ၄။ မြန်မာအသံ
DUB_PROVIDER_TTS_EN=piper               # ၅။ အင်္ဂလိပ်အသံ
DUB_PROVIDER_LIPSYNC=gpu_worker         # ၆။ နှုတ်ခမ်းချိန် (optional, နောက်ဆုံး)
```

သိမ်းပြီးရင် —

```bash
sudo docker compose up -d
sudo docker compose logs -f
```

တစ်ခုပြောင်းတိုင်း ဗီဒီယိုတိုလေးနဲ့ ပြန်စမ်းပါ။ ဒီလိုလုပ်မှ ပြဿနာတက်ရင်
ဘယ်အဆင့်က ပြဿနာလဲ ချက်ချင်း သိပါတယ်။

local model တွေအတွက် python package တွေ ထပ်လိုပါတယ် —
`backend/requirements.txt` ထဲက comment ထားတဲ့ စာကြောင်းတွေကို ဖွင့်ပြီး
`sudo docker compose up -d --build` ပြန်လုပ်ပါ။ ပထမဆုံးအကြိမ် run တဲ့အခါ
model weight တွေ ဒေါင်းလို့ ကြာပါတယ်။

## အဆင့် ၁၁ — နောက်ထပ် update တင်နည်း

```bash
cd /opt/dub
sudo git pull
sudo docker compose up -d --build
cd frontend && sudo npm ci && sudo npm run build
sudo cp -r dist/* /var/www/dub/
```

ဒါမှမဟုတ် တစ်ကြောင်းတည်းနဲ့ —

```bash
cd /opt/dub && sudo git pull && sudo bash deploy/install-on-server.sh
```

## အဆင့် ၁၂ — ကုန်ကျစရိတ် ထိန်းနည်း

- **မသုံးတဲ့အခါ instance ကို ပိတ်ထားပါ** —
  `aws ec2 stop-instances --instance-ids i-xxxx` (EBS ခ ၂–၃ ဒေါ်လာပဲ ကျန်မယ်)
  ပြန်ဖွင့်ရင် `start-instances`၊ IP ပြောင်းသွားမှာ သတိပြုပါ
  (မပြောင်းစေချင်ရင် Elastic IP တွဲပါ)။
- **GPU box က lip-sync လုပ်မှပဲ ဖွင့်ပါ** — spot instance နဲ့ နာရီလိုက် ငှားပါ။
- **S3 lifecycle** က ရက် ၃၀ ကျော်ရင် source file တွေ အလိုအလျောက် ဖျက်ပေးပါတယ်။
- **Billing alarm** တစ်ခု ထားပါ — Billing console → Budgets → US$20 alert။

## အဆင့် ၁၃ — အကုန်ဖျက်ချင်ရင်

CloudShell မှာ —

```bash
cd dub
bash deploy/aws-deploy.sh destroy
```

EC2၊ IAM role၊ security group တွေ ဖျက်ပါတယ်။ **S3 bucket နဲ့ secret ကိုတော့
မဖျက်ပါဘူး** (data မပျောက်အောင် တမင်ချန်ထားတာပါ)။ တကယ်ဖျက်ချင်ရင် —

```bash
aws s3 rb s3://dub-studio-media-<account-id> --force
aws secretsmanager delete-secret --secret-id dub-studio/gemini --force-delete-without-recovery
```

---

## ပြဿနာတက်ရင်

| အဖြစ်အပျက် | စစ်ရမယ့်နေရာ |
|---|---|
| browser မှာ ဘာမှမပေါ် | bootstrap မပြီးသေး — `sudo tail -f /var/log/dub-bootstrap.log` |
| `502 Bad Gateway` | API မတက်သေး — `sudo docker compose logs api` |
| upload မရ (403) | S3 CORS မှာ သင့် domain မပါ၊ ဒါမှမဟုတ် presigned URL သက်တမ်းကုန် |
| အကုန် `mock-` လို့ပြ | provider import မအောင် — Settings page နဲ့ API log ကြည့်ပါ |
| စာကြောင်းတွေ `long` ပြ | စာကို တိုအောင်ပြင် ဒါမှမဟုတ် speed လျှော့ပြီး Re-voice |
| SSH မဝင်ရ | သင့် IP ပြောင်းသွားပြီ — security group မှာ port 22 ကို ပြန်ဖွင့်ပါ |
| memory မလောက် | `t3.medium` ပြောင်းပါ ဒါမှမဟုတ် swap 2GB ထည့်ပါ |

အသေးစိတ် operations အတွက် `docs/OPERATIONS.md` ကို ဖတ်ပါ။
