import os
import json
import numpy as np
from PIL import Image
from flask import Flask, render_template, request, jsonify, send_from_directory
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

DB_FILE = 'students_db.json'

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

def save_db(data):
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def validate_and_process_omr(image_path, total_questions, q_type):
    try:
        img = Image.open(image_path).convert('L')
        img_np = np.array(img)
        h, w = img_np.shape

        if h < 300 or w < 200:
            return {"status": "rejected", "message": "REJECTED: Suuraan ergame kun waraqaa deebii (OMR Sheet) miti! Maaloo waraqaa deebii sirrii ta'e kaasaa."}

        std_dev = np.std(img_np)
        if std_dev < 15:
            return {"status": "rejected", "message": "REJECTED: Suuraan kun ifa hin qabu ykn waraqaa duwwaa dha. Please upload a valid OMR sheet."}

        binary = img_np < 120
        options = ['A', 'B', 'C', 'D', 'E'] if q_type == 'mcq5' else (['T', 'F'] if q_type == 'true_false' else ['A', 'B', 'C', 'D'])

        scanned_answers = {}
        row_height = h / total_questions

        for q in range(1, total_questions + 1):
            row_data = binary[int((q-1)*row_height):int(q*row_height), :]
            col_width = w / len(options)

            dark_counts = []
            for idx, opt in enumerate(options):
                col_box = row_data[:, int(idx*col_width):int((idx+1)*col_width)]
                black_count = np.sum(col_box)
                dark_counts.append((black_count, opt))

            dark_counts.sort(key=lambda x: x[0], reverse=True)
            highest, opt_high = dark_counts[0]
            second_high, _ = dark_counts[1]

            if highest < 50:
                scanned_answers[str(q)] = "Hin Deebisne"
            elif highest < (second_high * 1.25):
                scanned_answers[str(q)] = "Iddoo-Hin-Ifne (Unclear)"
            else:
                scanned_answers[str(q)] = opt_high

        return {"status": "success", "answers": scanned_answers}
    except Exception as e:
        print("Validation Error:", e)
        return {"status": "rejected", "message": "REJECTED: Suuraa kana dubbisuun hin danda'amne."}

@app.route('/')
def admin_dashboard():
    return render_template('admin.html')

@app.route('/portal')
def student_portal():
    return render_template('portal.html')

@app.route('/api/grade-scan', methods=['POST'])
def grade_scan():
    student_id = request.form.get('student_id', '').strip()
    name = request.form.get('name', '').strip()
    school_name = request.form.get('school_name', '').strip()
    grade_class = request.form.get('grade_class', '').strip()
    subject = request.form.get('subject', '').strip()
    question_type = request.form.get('question_type', 'mcq4')

    answer_key_raw = request.form.get('answer_key', '{}')
    answer_key = json.loads(answer_key_raw)
    total_questions = len(answer_key)

    if not student_id or not name:
        return jsonify({"success": False, "message": "Maqaa fi ID barataa guutuun dirqama!"})

    if 'omr_image' not in request.files:
        return jsonify({"success": False, "message": "Suuraan waraqaa deebii (OMR Image) hin argamne!"})

    file = request.files['omr_image']
    if file.filename == '':
        return jsonify({"success": False, "message": "Suuraan hin filatamne!"})

    img_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(img_path)

    scan_result = validate_and_process_omr(img_path, total_questions, question_type)
    if scan_result["status"] == "rejected":
        return jsonify({"success": False, "message": scan_result["message"]})

    student_answers = scan_result["answers"]
    correct_count = 0
    details = []

    for q, correct_ans in answer_key.items():
        student_ans = student_answers.get(str(q), "Hin Deebisne")

        if student_ans == "Iddoo-Hin-Ifne (Unclear)":
            status = "Sirreeffamuu Qaba (Unclear Mark)"
            is_correct = False
        elif student_ans == "Hin Deebisne":
            status = "Hin Deebisne (Unanswered)"
            is_correct = False
        else:
            is_correct = (str(student_ans).strip().upper() == str(correct_ans).strip().upper())
            if is_correct:
                correct_count += 1
            status = "Sirrii / Correct" if is_correct else "Dogoggora / Wrong"

        details.append({
            "question": q,
            "student_ans": student_ans,
            "correct_ans": correct_ans,
            "status": status
        })

    score = int((correct_count / total_questions) * 100) if total_questions > 0 else 0

    student_record = {
        "id": student_id,
        "name": name,
        "school_name": school_name,
        "grade_class": grade_class,
        "subject": subject,
        "question_type": question_type,
        "score": score,
        "correct_count": correct_count,
        "total_questions": total_questions,
        "details": details
    }

    db = load_db()
    db = [s for s in db if str(s.get('id')).strip() != str(student_id).strip()]
    db.append(student_record)
    save_db(db)

    return jsonify({"success": True, "message": "Waraqaan deebii milkaa'inaan scan ta'ee soroorfameera!", "record": student_record})

@app.route('/api/students', methods=['GET', 'DELETE'])
def manage_students():
    db = load_db()
    if request.method == 'GET':
        return jsonify(db)
    elif request.method == 'DELETE':
        student_id = request.args.get('id')
        if not student_id:
            return jsonify({"success": False, "message": "ID barataa hin argamne!"})

        new_db = [s for s in db if str(s.get('id', '')).strip() != str(student_id).strip()]
        save_db(new_db)
        return jsonify({"success": True, "message": "Galmeen barataa milkaa'inaan haqameera!"})

@app.route('/api/student-portal-search', methods=['POST'])
def student_portal_search():
    data = request.json
    s_id = str(data.get('student_id', '')).strip()
    s_school = str(data.get('school_name', '')).strip().lower()
    s_class = str(data.get('grade_class', '')).strip().lower()

    db = load_db()
    for s in db:
        if str(s.get('id')).strip() == s_id and \
           s_school in str(s.get('school_name', '')).strip().lower() and \
           s_class in str(s.get('grade_class', '')).strip().lower():
            return jsonify({"found": True, "record": s})

    return jsonify({"found": False, "message": "Odeeffannoon Barataa Hin Argamne!"})

@app.route('/api/generate-pdf', methods=['POST'])
def generate_pdf():
    school_name = request.form.get('school_name', '')
    exam_title = request.form.get('exam_title', '')
    subject = request.form.get('subject', '')
    total_q = int(request.form.get('total_questions', 20))
    q_type = request.form.get('question_type', 'mcq4')
    columns = int(request.form.get('columns', 2))
    lang_mode = request.form.get('lang_mode', 'bilingual')

    logo_path = None
    if 'logo_file' in request.files:
        file = request.files['logo_file']
        if file.filename != '':
            logo_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(logo_path)

    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], 'OMR_Answer_Sheet.pdf')
    c = canvas.Canvas(pdf_path, pagesize=letter)

    c.rect(25, 765, 15, 15, fill=1)
    c.rect(572, 765, 15, 15, fill=1)
    c.rect(25, 30, 15, 15, fill=1)
    c.rect(572, 30, 15, 15, fill=1)

    y = 745
    if logo_path and os.path.exists(logo_path):
        try:
            c.drawImage(logo_path, 45, y - 40, width=45, height=45, preserveAspectRatio=True)
        except:
            pass

    if school_name:
        c.setFont("Helvetica-Bold", 13)
        c.drawCentredString(320, y, school_name.upper())
        y -= 18

    if exam_title:
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(320, y, exam_title.upper())
        y -= 16

    c.setFont("Helvetica", 9)
    c.drawCentredString(320, y, f"Barnoota / Subject: {subject} | Type: {q_type.upper()}")
    y -= 25

    c.setFont("Helvetica", 8)
    c.drawString(45, y, "Maqaa Barataa / Student Name: _____________________   ID: _________   Kutaa / Class: _________")
    y -= 12
    c.line(40, y, 570, y)
    y -= 25

    col_width = 520 / columns
    start_y = y
    q_per_col = (total_q + columns - 1) // columns
    current_col = 0
    q_in_col = 0

    for q in range(1, total_q + 1):
        x = 45 + (current_col * col_width)
        if q_type == 'true_false':
            opt_str = f"{q:2d}.   [ T ]     [ F ]"
        elif q_type == 'mcq5':
            opt_str = f"{q:2d}.   (A)   (B)   (C)   (D)   (E)"
        else:
            opt_str = f"{q:2d}.   (A)   (B)   (C)   (D)"

        c.setFont("Helvetica", 9)
        c.drawString(x, y, opt_str)
        y -= 20
        q_in_col += 1

        if q_in_col >= q_per_col and current_col < columns - 1:
            current_col += 1
            q_in_col = 0
            y = start_y

    c.save()
    return jsonify({"download_url": "/api/download-pdf"})

@app.route('/api/download-pdf', methods=['GET'])
def download_pdf():
    return send_from_directory(app.config['UPLOAD_FOLDER'], 'OMR_Answer_Sheet.pdf', as_attachment=True)

@app.route('/api/download-result-pdf', methods=['POST'])
def generate_result_pdf():
    data = request.json
    student = data.get('student', {})
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], f"Result_{student.get('id', 'student')}.pdf")
    c = canvas.Canvas(pdf_path, pagesize=letter)

    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(300, 750, "BU'AA QORMAATAA BARATAA / STUDENT RESULT REPORT")

    c.setFont("Helvetica", 10)
    c.drawString(50, 715, f"Mana Barumsaa: {student.get('school_name')}")
    c.drawString(350, 715, f"ID: {student.get('id')}")
    c.drawString(50, 695, f"Maqaa Barataa: {student.get('name')}")
    c.drawString(350, 695, f"Kutaa: {student.get('grade_class')}")
    c.drawString(50, 675, f"Barnoota: {student.get('subject')}")
    c.line(40, 665, 570, 665)

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, 640, f"Qabxii Waliigalaa: {student.get('score')}% ({student.get('correct_count')}/{student.get('total_questions')})")

    y = 600
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Gaaffii")
    c.drawString(150, y, "Deebii Barataa")
    c.drawString(300, y, "Deebii Sirrii")
    c.drawString(430, y, "Haala")
    y -= 15
    c.line(40, y, 570, y)

    c.setFont("Helvetica", 9)
    for d in student.get('details', []):
        if y < 50:
            c.showPage()
            y = 720
        y -= 18
        c.drawString(50, y, f"{d.get('question')}")
        c.drawString(150, y, str(d.get('student_ans')))
        c.drawString(300, y, str(d.get('correct_ans')))
        c.drawString(430, y, str(d.get('status')))

    c.save()
    return jsonify({"download_url": f"/api/download-result-file/{os.path.basename(pdf_path)}"})

@app.route('/api/download-result-file/<filename>', methods=['GET'])
def download_result_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
