"""
MCQ সলভার v2.0 - ৩ AI + সব ফিচার
"""

from flask import Flask, render_template, request, jsonify, send_file
import google.generativeai as genai
from groq import Groq
import requests as http_requests
import json
import re
import os
import io
import uuid
import time
from datetime import datetime
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'mcq-solver-2024')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

GEMINI_KEY = os.environ.get('GEMINI_API_KEY', '')
GROQ_KEY = os.environ.get('GROQ_API_KEY', '')
TOGETHER_KEY = os.environ.get('TOGETHER_API_KEY', '')

gemini_model = None
groq_client = None
ai_count = 0

if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)
        gemini_model = genai.GenerativeModel('gemini-2.0-flash')
        ai_count += 1
        print("AI 1: Gemini OK")
    except Exception as e:
        print(f"Gemini error: {e}")

if GROQ_KEY:
    try:
        groq_client = Groq(api_key=GROQ_KEY)
        ai_count += 1
        print("AI 2: Groq OK")
    except Exception as e:
        print(f"Groq error: {e}")

if TOGETHER_KEY:
    ai_count += 1
    print("AI 3: Together OK")

print(f"Total AI: {ai_count}")

sessions = {}


def extract_json(text, as_list=False):
    if not text:
        return [] if as_list else {}
    try:
        text = text.strip()
        m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if m:
            text = m.group(1)
        if as_list:
            m2 = re.search(r'\[[\s\S]*\]', text)
            if m2:
                return json.loads(m2.group())
        else:
            m2 = re.search(r'\{[\s\S]*\}', text)
            if m2:
                return json.loads(m2.group())
    except json.JSONDecodeError:
        pass
    if as_list:
        return []
    return {
        "explanation": text[:1000] if text else "ব্যাখ্যা পাওয়া যায়নি",
        "sources": ["তথ্যসূত্র যাচাই প্রয়োজন"],
        "confidence": 0.4
    }


def clean_sessions():
    now = time.time()
    to_delete = [sid for sid, data in sessions.items() if now - data.get('created_at', 0) > 3600]
    for sid in to_delete:
        del sessions[sid]


def ask_gemini(prompt):
    if not gemini_model:
        return None
    try:
        response = gemini_model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=0.2, max_output_tokens=2500)
        )
        return response.text
    except Exception as e:
        print(f"Gemini err: {e}")
        return None


def ask_groq(prompt):
    if not groq_client:
        return None
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "তুমি বাংলাদেশের শিক্ষক। বাংলায় ও JSON এ উত্তর দাও।"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2, max_tokens=2500
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Groq err: {e}")
        return None


def ask_together(prompt):
    if not TOGETHER_KEY:
        return None
    try:
        response = http_requests.post(
            "https://api.together.xyz/v1/chat/completions",
            headers={"Authorization": f"Bearer {TOGETHER_KEY}", "Content-Type": "application/json"},
            json={
                "model": "mistralai/Mixtral-8x7B-Instruct-v0.1",
                "messages": [
                    {"role": "system", "content": "তুমি বাংলাদেশের শিক্ষক। বাংলায় ও JSON এ উত্তর দাও।"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2, "max_tokens": 2500
            },
            timeout=30
        )
        data = response.json()
        return data['choices'][0]['message']['content']
    except Exception as e:
        print(f"Together err: {e}")
        return None


def parse_mcqs(raw_text):
    prompt = f"""নিচের টেক্সট থেকে শুধু MCQ প্রশ্ন extract করো।

নিয়ম:
- শুধু ৪টি অপশন + ১টি উত্তর আছে এমন প্রশ্ন নাও
- ওয়াটারমার্ক, ওয়েবসাইট নাম, প্রমোশনাল তথ্য, "কোন সালে এসেছিল" বাদ দাও
- পেজ নম্বর, বিজ্ঞাপন বাদ দাও

JSON array দাও (শুধু JSON):
[
  {{
    "question_no": 1,
    "question": "প্রশ্ন",
    "option_a": "অপশন ক",
    "option_b": "অপশন খ",
    "option_c": "অপশন গ",
    "option_d": "অপশন ঘ",
    "correct_answer": "ক",
    "correct_option_text": "সঠিক অপশনের টেক্সট"
  }}
]

টেক্সট:
\"\"\"{raw_text}\"\"\"
"""
    for fn_name, fn in [("Gemini", ask_gemini), ("Groq", ask_groq), ("Together", ask_together)]:
        result = fn(prompt)
        if result:
            parsed = extract_json(result, as_list=True)
            if parsed and len(parsed) > 0:
                print(f"{fn_name}: {len(parsed)} MCQ found")
                return parsed
        time.sleep(0.3)
    return []


def parse_image(image_path):
    if not gemini_model:
        return []
    try:
        import PIL.Image
        img = PIL.Image.open(image_path)
        vision = genai.GenerativeModel('gemini-2.0-flash')
        prompt = """ছবি থেকে MCQ extract করো। ওয়াটারমার্ক/প্রমো বাদ দাও।
JSON array দাও:
[{"question_no":1,"question":"...","option_a":"...","option_b":"...","option_c":"...","option_d":"...","correct_answer":"ক","correct_option_text":"..."}]"""
        r = vision.generate_content([prompt, img])
        return extract_json(r.text, as_list=True)
    except Exception as e:
        print(f"Image err: {e}")
        return []


def generate_explanation(mcq, subject=""):
    subj = f"\nবিষয়: {subject}" if subject else ""
    prompt = f"""তুমি বাংলাদেশের অভিজ্ঞ একাডেমিক শিক্ষক।{subj}

MCQ:
প্রশ্ন: {mcq.get('question', '')}
(ক) {mcq.get('option_a', '')}
(খ) {mcq.get('option_b', '')}
(গ) {mcq.get('option_c', '')}
(ঘ) {mcq.get('option_d', '')}
সঠিক উত্তর: ({mcq.get('correct_answer', '')}) {mcq.get('correct_option_text', '')}

করণীয়:
১। সঠিক উত্তর কেন সঠিক - বিস্তারিত তথ্যসহ ব্যাখ্যা
২। বাকি ৩টি অপশন কেন ভুল - সংক্ষেপে
৩। বাংলাদেশ প্রেক্ষাপটে প্রাসঙ্গিক তথ্য
৪। কমপক্ষে ২টি বাংলাদেশী সোর্স দাও

সোর্স:
- কৃষি: BARI, BRRI, BINA, কৃষি তথ্য সার্ভিস (AIS), কৃষি বাতায়ন, BAU
- বিজ্ঞান: ঢাকা বিশ্ববিদ্যালয়, BCSIR, NCTB পাঠ্যপুস্তক
- সাধারণ: বাংলাপিডিয়া, BBS, জাতীয় তথ্য বাতায়ন

JSON:
{{
  "explanation": "বিস্তারিত ব্যাখ্যা...",
  "sources": ["সোর্স ১", "সোর্স ২"],
  "confidence": 0.95,
  "key_point": "মূল পয়েন্ট"
}}"""

    results = {}
    g = ask_gemini(prompt)
    if g:
        results['gemini'] = extract_json(g)
    time.sleep(0.5)
    q = ask_groq(prompt)
    if q:
        results['groq'] = extract_json(q)
    time.sleep(0.5)
    t = ask_together(prompt)
    if t:
        results['together'] = extract_json(t)

    if not results:
        return {"explanation": "ব্যাখ্যা তৈরি যায়নি। API Key চেক করুন।", "sources": ["তথ্যসূত্র পাওয়া যায়নি"], "key_point": ""}

    all_sources = []
    best = None
    best_score = -1
    for name, r in results.items():
        if not isinstance(r, dict):
            continue
        for s in r.get('sources', []):
            if s and s not in all_sources:
                all_sources.append(s)
        score = r.get('confidence', 0.5)
        exp = r.get('explanation', '')
        if len(exp) > 200:
            score += 0.1
        if len(exp) > 400:
            score += 0.1
        if name == 'gemini':
            score += 0.05
        if len(r.get('sources', [])) >= 2:
            score += 0.1
        if score > best_score:
            best_score = score
            best = r

    if best:
        best['sources'] = all_sources[:5]
        if len(best['sources']) < 2:
            defaults = ["বাংলাপিডিয়া - banglapedia.org", "জাতীয় তথ্য বাতায়ন - bangladesh.gov.bd"]
            for d in defaults:
                if d not in best['sources']:
                    best['sources'].append(d)
                if len(best['sources']) >= 2:
                    break
        return best

    first = list(results.values())[0]
    if isinstance(first, dict):
        first['sources'] = all_sources[:5] if all_sources else ["তথ্যসূত্র যাচাই প্রয়োজন"]
        return first
    return {"explanation": str(first), "sources": ["তথ্যসূত্র যাচাই প্রয়োজন"], "key_point": ""}
  # ═══════ API ROUTES ═══════

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/status')
def api_status():
    return jsonify({"gemini": gemini_model is not None, "groq": groq_client is not None, "together": bool(TOGETHER_KEY), "total_ai": ai_count})


@app.route('/api/parse-text', methods=['POST'])
def api_parse_text():
    try:
        clean_sessions()
        data = request.get_json()
        text = data.get('text', '')
        if not text.strip():
            return jsonify({"error": "টেক্সট দিন"}), 400
        if len(text) > 50000:
            return jsonify({"error": "টেক্সট অনেক বড়"}), 400
        mcqs = parse_mcqs(text)
        if not mcqs:
            return jsonify({"error": "MCQ পাওয়া যায়নি। ফরম্যাট চেক করুন।"}), 400
        sid = str(uuid.uuid4())[:8]
        sessions[sid] = {'mcqs': mcqs, 'header': {}, 'created_at': time.time()}
        return jsonify({"session_id": sid, "mcqs": mcqs, "count": len(mcqs)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/parse-file', methods=['POST'])
def api_parse_file():
    try:
        clean_sessions()
        if 'file' not in request.files:
            return jsonify({"error": "ফাইল দিন"}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "ফাইল সিলেক্ট করুন"}), 400
        ext = file.filename.rsplit('.', 1)[-1].lower()
        filepath = f"/tmp/{uuid.uuid4()}.{ext}"
        file.save(filepath)
        mcqs = []
        if ext == 'pdf':
            import pdfplumber
            text = ""
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text += t + "\n"
            mcqs = parse_mcqs(text) if text.strip() else parse_image(filepath)
        elif ext in ['png', 'jpg', 'jpeg', 'webp', 'bmp']:
            mcqs = parse_image(filepath)
        else:
            return jsonify({"error": "PDF বা ছবি দিন"}), 400
        try:
            os.remove(filepath)
        except:
            pass
        if not mcqs:
            return jsonify({"error": "MCQ পাওয়া যায়নি"}), 400
        sid = str(uuid.uuid4())[:8]
        sessions[sid] = {'mcqs': mcqs, 'header': {}, 'created_at': time.time()}
        return jsonify({"session_id": sid, "mcqs": mcqs, "count": len(mcqs)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/explain', methods=['POST'])
def api_explain():
    try:
        data = request.get_json()
        sid = data.get('session_id', '')
        subject = data.get('subject', '')
        header = data.get('header_info', {})
        if sid not in sessions:
            return jsonify({"error": "সেশন মেয়াদোত্তীর্ণ। আবার সাবমিট করুন।"}), 404
        mcqs = sessions[sid]['mcqs']
        sessions[sid]['header'] = header
        explained = []
        for i, mcq in enumerate(mcqs):
            print(f"Explaining {i+1}/{len(mcqs)}...")
            result = generate_explanation(mcq, subject)
            mcq_ex = {**mcq, "explanation": result.get("explanation", ""), "sources": result.get("sources", []), "key_point": result.get("key_point", "")}
            explained.append(mcq_ex)
            if i < len(mcqs) - 1:
                time.sleep(2)
        sessions[sid]['mcqs'] = explained
        return jsonify({"session_id": sid, "mcqs": explained, "count": len(explained)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/export/html', methods=['POST'])
def export_html():
    data = request.get_json()
    sid = data.get('session_id', '')
    if sid not in sessions:
        return jsonify({"error": "সেশন নেই"}), 404
    s = sessions[sid]
    html = build_html(s['mcqs'], s.get('header', {}))
    buf = io.BytesIO(html.encode('utf-8'))
    buf.seek(0)
    return send_file(buf, mimetype='text/html', as_attachment=True, download_name=f"mcq_{datetime.now().strftime('%Y%m%d_%H%M')}.html")


@app.route('/api/export/word', methods=['POST'])
def export_word():
    data = request.get_json()
    sid = data.get('session_id', '')
    if sid not in sessions:
        return jsonify({"error": "সেশন নেই"}), 404
    s = sessions[sid]
    buf = build_word(s['mcqs'], s.get('header', {}))
    return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document', as_attachment=True, download_name=f"mcq_{datetime.now().strftime('%Y%m%d_%H%M')}.docx")


@app.route('/api/export/pdf', methods=['POST'])
def export_pdf():
    data = request.get_json()
    sid = data.get('session_id', '')
    if sid not in sessions:
        return jsonify({"error": "সেশন নেই"}), 404
    s = sessions[sid]
    html = build_html(s['mcqs'], s.get('header', {}), for_print=True)
    buf = io.BytesIO(html.encode('utf-8'))
    buf.seek(0)
    return send_file(buf, mimetype='text/html', as_attachment=True, download_name=f"mcq_PRINT_{datetime.now().strftime('%Y%m%d_%H%M')}.html")
  # ═══════ HTML BUILDER ═══════

def build_html(mcqs, header, for_print=False):
    header_html = ""
    if header and any(v for v in header.values() if v):
        header_html = f"""<div class="eh">
<h1>{header.get('institution', '') or 'প্রতিষ্ঠান'}</h1>
<h2>{header.get('exam_name', '') or 'পরীক্ষা'}</h2>
<table class="it">
<tr><td><b>সাল:</b> {header.get('year', '-')}</td><td><b>পূর্ণমান:</b> {header.get('total_marks', '-')}</td><td><b>সময়:</b> {header.get('duration', '-')}</td></tr>
<tr><td><b>নেগেটিভ:</b> {header.get('negative_marking', '-')}</td><td colspan="2"><b>নির্দেশনা:</b> {header.get('instructions', '-')}</td></tr>
</table></div>"""

    qs = ""
    for i, m in enumerate(mcqs, 1):
        srcs = ', '.join(m.get('sources', [])) or 'N/A'
        ca = (m.get('correct_answer', '') or '').lower()
        omap = {'ক': 'a', 'খ': 'b', 'গ': 'c', 'ঘ': 'd', 'a': 'a', 'b': 'b', 'c': 'c', 'd': 'd'}
        ck = omap.get(ca, '')

        def oc(k):
            return ' ok' if k == ck else ''

        qs += f"""<div class="qc">
<div class="qn">প্রশ্ন {i}</div>
<div class="qt">{m.get('question', '')}</div>
<div class="op{oc('a')}">(ক) {m.get('option_a', '')}</div>
<div class="op{oc('b')}">(খ) {m.get('option_b', '')}</div>
<div class="op{oc('c')}">(গ) {m.get('option_c', '')}</div>
<div class="op{oc('d')}">(ঘ) {m.get('option_d', '')}</div>
<div class="an">✅ সঠিক উত্তর: ({m.get('correct_answer', '')}) {m.get('correct_option_text', '')}</div>
<div class="ex"><b>📖 ব্যাখ্যা:</b><p>{m.get('explanation', 'ব্যাখ্যা পাওয়া যায়নি')}</p>
<div class="sr"><b>📚 তথ্যসূত্র:</b> [{srcs}]</div></div></div>"""

    pjs = '<script>window.onload=function(){window.print()}</script>' if for_print else ''

    return f"""<!DOCTYPE html>
<html lang="bn"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MCQ সমাধান</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Bengali:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Noto Sans Bengali',sans-serif;font-size:14px;line-height:1.8;color:#1a1a1a;padding:25px;background:#fff}}
.eh{{text-align:center;border:2px solid #1a237e;padding:22px;margin-bottom:28px;border-radius:10px;background:#f8f9ff}}
.eh h1{{font-size:21px;color:#1a237e}}.eh h2{{font-size:16px;color:#333;margin:5px 0 10px}}
.it{{width:100%;border-collapse:collapse;margin-top:8px}}.it td{{padding:6px 12px;border:1px solid #c5cae9;font-size:13px}}
.qc{{border:1px solid #e0e0e0;border-radius:10px;padding:20px;margin-bottom:20px;page-break-inside:avoid;background:#fafbff}}
.qn{{font-weight:700;color:#1565c0;font-size:15px;margin-bottom:8px}}
.qt{{font-size:15px;font-weight:600;margin-bottom:12px;color:#212121;line-height:1.7}}
.op{{padding:6px 16px;margin:4px 0;border-radius:6px;font-size:14px}}
.ok{{background:#e8f5e9;border-left:4px solid #2e7d32;font-weight:600;color:#1b5e20}}
.an{{background:#e3f2fd;padding:11px 16px;border-radius:7px;margin:14px 0;font-weight:600;color:#0d47a1;font-size:14px}}
.ex{{background:#fff;border:1px solid #e0e0e0;padding:16px;border-radius:8px;font-size:13.5px;line-height:1.9}}
.ex p{{margin:8px 0;text-align:justify}}
.sr{{margin-top:12px;padding-top:10px;border-top:1px dashed #ccc;font-size:12.5px;color:#555}}
.ft{{text-align:center;margin-top:30px;padding-top:15px;border-top:1px solid #ddd;font-size:12px;color:#999}}
@media print{{body{{padding:12px;font-size:12px}}.qc{{border:1px solid #ccc}}.eh{{border:2px solid #000}}}}
</style>{pjs}</head><body>
{header_html}
{qs}
<div class="ft">MCQ সলভার | {datetime.now().strftime('%d-%m-%Y %H:%M')}</div>
</body></html>"""


# ═══════ WORD BUILDER ═══════

def build_word(mcqs, header):
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = 'Noto Sans Bengali'
    style.font.size = Pt(11)

    if header and any(v for v in header.values() if v):
        p1 = doc.add_paragraph()
        p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r1 = p1.add_run(header.get('institution', '') or '')
        r1.bold = True
        r1.font.size = Pt(16)
        p2 = doc.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r2 = p2.add_run(header.get('exam_name', '') or '')
        r2.bold = True
        r2.font.size = Pt(13)
        info = []
        for k, l in [('year', 'সাল'), ('total_marks', 'পূর্ণমান'), ('duration', 'সময়'), ('negative_marking', 'নেগেটিভ')]:
            if header.get(k):
                info.append(f"{l}: {header[k]}")
        if info:
            p3 = doc.add_paragraph(' | '.join(info))
            p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if header.get('instructions'):
            p4 = doc.add_paragraph(f"নির্দেশনা: {header['instructions']}")
            p4.alignment = WD_ALIGN_PARAGRAPH.CENTER
        doc.add_paragraph('━' * 55)

    for i, m in enumerate(mcqs, 1):
        pq = doc.add_paragraph()
        rq = pq.add_run(f"প্রশ্ন {i}। {m.get('question', '')}")
        rq.bold = True
        rq.font.size = Pt(12)
        for lbl, key in [('ক', 'option_a'), ('খ', 'option_b'), ('গ', 'option_c'), ('ঘ', 'option_d')]:
            po = doc.add_paragraph(f"    ({lbl}) {m.get(key, '')}")
            po.paragraph_format.space_after = Pt(2)
        pa = doc.add_paragraph()
        ra = pa.add_run(f"✅ সঠিক: ({m.get('correct_answer', '')}) {m.get('correct_option_text', '')}")
        ra.bold = True
        ra.font.color.rgb = RGBColor(0x1B, 0x5E, 0x20)
        exp = m.get('explanation', '')
        if exp:
            pe = doc.add_paragraph()
            pe.add_run("📖 ব্যাখ্যা: ").bold = True
            pe.add_run(exp).font.size = Pt(10.5)
        srcs = m.get('sources', [])
        if srcs:
            ps = doc.add_paragraph()
            rs = ps.add_run(f"📚 তথ্যসূত্র: [{', '.join(srcs)}]")
            rs.font.size = Pt(9.5)
            rs.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
        if i < len(mcqs):
            doc.add_paragraph('─' * 50)

    doc.add_paragraph()
    pf = doc.add_paragraph()
    pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rf = pf.add_run(f"MCQ সলভার | {datetime.now().strftime('%d-%m-%Y %H:%M')}")
    rf.font.size = Pt(9)
    rf.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


# ═══════ START ═══════

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"\nMCQ Solver v2.0 | AI: {ai_count} | Port: {port}\n")
    app.run(host='0.0.0.0', port=port, debug=False)
