from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import sqlite3, hashlib, io
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import inch
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'ssjcoe_rms_2024_secret'

DATABASE = 'results.db'
COLLEGE_NAME = "Shivajirao S. Jondhle College of Engineering & Technology"
COLLEGE_SHORT = "SSJCOE"

# ─── DB ───────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def init_db():
    conn = get_db(); c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, name TEXT NOT NULL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, name TEXT NOT NULL, department TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll_number TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
        name TEXT NOT NULL, branch TEXT NOT NULL,
        semester INTEGER NOT NULL, academic_year TEXT NOT NULL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, code TEXT NOT NULL,
        max_marks INTEGER DEFAULT 100, semester INTEGER NOT NULL, branch TEXT NOT NULL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS marks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL, subject_id INTEGER NOT NULL,
        marks_obtained REAL NOT NULL,
        FOREIGN KEY(student_id) REFERENCES students(id),
        FOREIGN KEY(subject_id) REFERENCES subjects(id),
        UNIQUE(student_id, subject_id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS notices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL, content TEXT NOT NULL,
        posted_by TEXT NOT NULL, role TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT)''')

    # Seed admin
    c.execute("INSERT OR IGNORE INTO admins (username,password,name) VALUES (?,?,?)",
              ('admin', hash_pw('admin123'), 'System Administrator'))
    # Seed teacher
    c.execute("INSERT OR IGNORE INTO teachers (username,password,name,department) VALUES (?,?,?,?)",
              ('teacher', hash_pw('teacher123'), 'Prof. Demo Teacher', 'Computer Science'))
    # Seed subjects CS Sem1
    for s in [('Mathematics I','MATH101',100,1,'CS'),('Physics','PHY101',100,1,'CS'),
              ('Chemistry','CHEM101',100,1,'CS'),('English','ENG101',100,1,'CS'),
              ('Programming Fundamentals','CS101',100,1,'CS')]:
        c.execute("INSERT OR IGNORE INTO subjects (name,code,max_marks,semester,branch) VALUES (?,?,?,?,?)", s)
    # Seed student
    c.execute("INSERT OR IGNORE INTO students (roll_number,password,name,branch,semester,academic_year) VALUES (?,?,?,?,?,?)",
              ('CS2024001', hash_pw('CS2024001'), 'Rahul Sharma', 'CS', 1, '2024-25'))
    # Seed notice
    now = datetime.now().strftime('%d %b %Y, %I:%M %p')
    c.execute("INSERT OR IGNORE INTO notices (title,content,posted_by,role,created_at) VALUES (?,?,?,?,?)",
              ('Welcome to SSJCOE Result Portal',
               'Dear Students and Faculty,\n\nWelcome to the Shivajirao S. Jondhle College of Engineering & Technology online result management portal. You can view your results and notices here.\n\nBest Regards,\nAdministration',
               'System Administrator', 'admin', now))
    conn.commit(); conn.close()

# ─── GRADE LOGIC ──────────────────────────────────────────────────────────────

def grade_info(pct):
    if pct >= 75: return 'Distinction', '#1a6b3c', '#d4edda', '🏆'
    if pct >= 60: return 'First Class', '#1a4f8b', '#cce5ff', '⭐'
    if pct >= 40: return 'Pass Class',  '#7a5c00', '#fff3cd', '✓'
    return 'Fail', '#c0392b', '#fdecea', '✗'

def get_result(student_id):
    conn = get_db()
    student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    rows = conn.execute("""SELECT s.name,s.code,s.max_marks,m.marks_obtained
        FROM marks m JOIN subjects s ON m.subject_id=s.id WHERE m.student_id=?""", (student_id,)).fetchall()
    conn.close()
    results, tot_obt, tot_max, fail_count = [], 0, 0, 0
    for r in rows:
        pct = round((r['marks_obtained']/r['max_marks'])*100, 2)
        g, gc, gbg, gi = grade_info(pct)
        if g == 'Fail': fail_count += 1
        results.append({'subject':r['name'],'code':r['code'],'max':r['max_marks'],
                        'obtained':r['marks_obtained'],'percentage':pct,
                        'grade':g,'grade_color':gc,'grade_bg':gbg})
        tot_obt += r['marks_obtained']; tot_max += r['max_marks']
    if tot_max > 0:
        op = round((tot_obt/tot_max)*100, 2)
        og, ogc, ogbg, ogi = ('Fail','#c0392b','#fdecea','✗') if fail_count else grade_info(op)
    else:
        op, og, ogc, ogbg, ogi = 0, 'N/A', '#888', '#f0f0f0', '—'
    return dict(student=student, results=results, total_obtained=tot_obt, total_max=tot_max,
                overall_percentage=op, overall_grade=og, grade_color=ogc, grade_bg=ogbg, grade_icon=ogi)

# ─── AUTH ─────────────────────────────────────────────────────────────────────

def role_required(role):
    def decorator(f):
        @wraps(f)
        def wrap(*a, **kw):
            if session.get('role') != role:
                return redirect(url_for('login'))
            return f(*a, **kw)
        return wrap
    return decorator

# ─── LOGIN ────────────────────────────────────────────────────────────────────

@app.route('/')
def index(): return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        role, user, pw = request.form['role'], request.form['username'], hash_pw(request.form['password'])
        conn = get_db()
        if role == 'admin':
            u = conn.execute("SELECT * FROM admins WHERE username=? AND password=?", (user,pw)).fetchone()
            if u: session.update({'role':'admin','user_id':u['id'],'user_name':u['name']}); conn.close(); return redirect('/admin/dashboard')
        elif role == 'teacher':
            u = conn.execute("SELECT * FROM teachers WHERE username=? AND password=?", (user,pw)).fetchone()
            if u: session.update({'role':'teacher','user_id':u['id'],'user_name':u['name']}); conn.close(); return redirect('/teacher/dashboard')
        elif role == 'student':
            u = conn.execute("SELECT * FROM students WHERE roll_number=? AND password=?", (user,pw)).fetchone()
            if u: session.update({'role':'student','user_id':u['id'],'user_name':u['name']}); conn.close(); return redirect('/student/dashboard')
        conn.close()
        flash('Invalid credentials. Please try again.', 'error')
    return render_template('login.html', college=COLLEGE_NAME, college_short=COLLEGE_SHORT)

@app.route('/logout')
def logout(): session.clear(); return redirect('/login')

# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/admin/dashboard')
@role_required('admin')
def admin_dashboard():
    conn = get_db()
    teachers = conn.execute("SELECT * FROM teachers").fetchall()
    students  = conn.execute("SELECT * FROM students").fetchall()
    notices   = conn.execute("SELECT * FROM notices ORDER BY id DESC LIMIT 5").fetchall()
    # stats
    total_students = len(students)
    stats = {'Distinction':0,'First Class':0,'Pass Class':0,'Fail':0,'N/A':0}
    for s in students:
        d = get_result(s['id'])
        stats[d['overall_grade']] = stats.get(d['overall_grade'], 0) + 1
    conn.close()
    return render_template('admin_dashboard.html', teachers=teachers, students=students,
                           notices=notices, stats=stats, college=COLLEGE_NAME, college_short=COLLEGE_SHORT)

# ── Teachers CRUD ──
@app.route('/admin/teachers')
@role_required('admin')
def admin_teachers():
    conn = get_db()
    teachers = conn.execute("SELECT * FROM teachers ORDER BY name").fetchall()
    conn.close()
    return render_template('admin_teachers.html', teachers=teachers, college=COLLEGE_NAME)

@app.route('/admin/add_teacher', methods=['POST'])
@role_required('admin')
def add_teacher():
    conn = get_db()
    try:
        conn.execute("INSERT INTO teachers (username,password,name,department) VALUES (?,?,?,?)",
                     (request.form['username'].strip(), hash_pw(request.form['password']),
                      request.form['name'].strip(), request.form['department'].strip()))
        conn.commit(); flash(f"Teacher '{request.form['name']}' added!", 'success')
    except sqlite3.IntegrityError: flash('Username already exists!', 'error')
    finally: conn.close()
    return redirect('/admin/teachers')

@app.route('/admin/edit_teacher/<int:tid>', methods=['GET','POST'])
@role_required('admin')
def edit_teacher(tid):
    conn = get_db()
    if request.method == 'POST':
        pw_update = f", password='{hash_pw(request.form['password'])}'" if request.form.get('password') else ''
        conn.execute(f"UPDATE teachers SET name=?, username=?, department=? {pw_update} WHERE id=?",
                     (request.form['name'], request.form['username'], request.form['department'], tid))
        conn.commit(); conn.close()
        flash('Teacher updated!', 'success'); return redirect('/admin/teachers')
    t = conn.execute("SELECT * FROM teachers WHERE id=?", (tid,)).fetchone(); conn.close()
    return render_template('admin_edit_teacher.html', teacher=t, college=COLLEGE_NAME)

@app.route('/admin/delete_teacher/<int:tid>', methods=['POST'])
@role_required('admin')
def delete_teacher(tid):
    conn = get_db()
    t = conn.execute("SELECT name FROM teachers WHERE id=?", (tid,)).fetchone()
    conn.execute("DELETE FROM teachers WHERE id=?", (tid,)); conn.commit(); conn.close()
    flash(f"Teacher '{t['name']}' deleted.", 'success'); return redirect('/admin/teachers')

# ── Students CRUD ──
@app.route('/admin/students')
@role_required('admin')
def admin_students():
    conn = get_db()
    students = conn.execute("SELECT * FROM students ORDER BY branch,semester,name").fetchall()
    conn.close()
    return render_template('admin_students.html', students=students, college=COLLEGE_NAME)

@app.route('/admin/add_student', methods=['POST'])
@role_required('admin')
def admin_add_student():
    r = request.form
    conn = get_db()
    try:
        conn.execute("INSERT INTO students (roll_number,password,name,branch,semester,academic_year) VALUES (?,?,?,?,?,?)",
                     (r['roll_number'].strip(), hash_pw(r['roll_number'].strip()),
                      r['name'].strip(), r['branch'], int(r['semester']), r['academic_year'].strip()))
        conn.commit(); flash(f"Student '{r['name']}' added!", 'success')
    except sqlite3.IntegrityError: flash('Roll number already exists!', 'error')
    finally: conn.close()
    return redirect('/admin/students')

@app.route('/admin/edit_student/<int:sid>', methods=['GET','POST'])
@role_required('admin')
def edit_student(sid):
    conn = get_db()
    if request.method == 'POST':
        r = request.form
        conn.execute("UPDATE students SET name=?,roll_number=?,branch=?,semester=?,academic_year=? WHERE id=?",
                     (r['name'], r['roll_number'], r['branch'], int(r['semester']), r['academic_year'], sid))
        conn.commit(); conn.close(); flash('Student updated!', 'success'); return redirect('/admin/students')
    s = conn.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone(); conn.close()
    return render_template('admin_edit_student.html', student=s, college=COLLEGE_NAME)

@app.route('/admin/delete_student/<int:sid>', methods=['POST'])
@role_required('admin')
def admin_delete_student(sid):
    conn = get_db()
    s = conn.execute("SELECT name FROM students WHERE id=?", (sid,)).fetchone()
    conn.execute("DELETE FROM marks WHERE student_id=?", (sid,))
    conn.execute("DELETE FROM students WHERE id=?", (sid,)); conn.commit(); conn.close()
    flash(f"Student '{s['name']}' deleted.", 'success'); return redirect('/admin/students')

# ── Admin View All Results ──
@app.route('/admin/results')
@role_required('admin')
def admin_results():
    conn = get_db()
    students = conn.execute("SELECT * FROM students ORDER BY branch,semester,name").fetchall()
    summaries = [dict(id=s['id'],name=s['name'],roll=s['roll_number'],branch=s['branch'],semester=s['semester'],**{k:get_result(s['id'])[k] for k in ['overall_percentage','overall_grade','grade_color']}) for s in students]
    conn.close()
    return render_template('all_results.html', summaries=summaries, college=COLLEGE_NAME,
                           college_short=COLLEGE_SHORT, role='admin')

# ── Notices (Admin) ──
@app.route('/admin/notices')
@role_required('admin')
def admin_notices():
    conn = get_db()
    notices = conn.execute("SELECT * FROM notices ORDER BY id DESC").fetchall()
    conn.close()
    return render_template('admin_notices.html', notices=notices, college=COLLEGE_NAME)

@app.route('/admin/add_notice', methods=['POST'])
@role_required('admin')
def admin_add_notice():
    now = datetime.now().strftime('%d %b %Y, %I:%M %p')
    conn = get_db()
    conn.execute("INSERT INTO notices (title,content,posted_by,role,created_at) VALUES (?,?,?,?,?)",
                 (request.form['title'].strip(), request.form['content'].strip(),
                  session['user_name'], 'admin', now))
    conn.commit(); conn.close()
    flash('Notice posted!', 'success'); return redirect('/admin/notices')

@app.route('/admin/edit_notice/<int:nid>', methods=['GET','POST'])
@role_required('admin')
def admin_edit_notice(nid):
    conn = get_db()
    if request.method == 'POST':
        now = datetime.now().strftime('%d %b %Y, %I:%M %p')
        conn.execute("UPDATE notices SET title=?,content=?,updated_at=? WHERE id=?",
                     (request.form['title'], request.form['content'], now, nid))
        conn.commit(); conn.close(); flash('Notice updated!', 'success'); return redirect('/admin/notices')
    n = conn.execute("SELECT * FROM notices WHERE id=?", (nid,)).fetchone(); conn.close()
    return render_template('edit_notice.html', notice=n, college=COLLEGE_NAME, back_url='/admin/notices')

@app.route('/admin/delete_notice/<int:nid>', methods=['POST'])
@role_required('admin')
def admin_delete_notice(nid):
    conn = get_db()
    conn.execute("DELETE FROM notices WHERE id=?", (nid,)); conn.commit(); conn.close()
    flash('Notice deleted.', 'success'); return redirect('/admin/notices')

# ═══════════════════════════════════════════════════════════════════════════════
# TEACHER ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/teacher/dashboard')
@role_required('teacher')
def teacher_dashboard():
    conn = get_db()
    students = conn.execute("SELECT * FROM students ORDER BY branch,semester,name").fetchall()
    notices  = conn.execute("SELECT * FROM notices ORDER BY id DESC LIMIT 5").fetchall()
    # Analytics
    grade_counts = {'Distinction':0,'First Class':0,'Pass Class':0,'Fail':0}
    for s in students:
        d = get_result(s['id'])
        if d['overall_grade'] in grade_counts:
            grade_counts[d['overall_grade']] += 1
    conn.close()
    return render_template('teacher_dashboard.html', students=students, notices=notices,
                           grade_counts=grade_counts, college=COLLEGE_NAME, college_short=COLLEGE_SHORT)

@app.route('/teacher/enter_marks/<int:sid>', methods=['GET','POST'])
@role_required('teacher')
def enter_marks(sid):
    conn = get_db()
    student  = conn.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    subjects = conn.execute("SELECT * FROM subjects WHERE semester=? AND branch=?",
                            (student['semester'], student['branch'])).fetchall()
    if request.method == 'POST':
        for subj in subjects:
            v = request.form.get(f'marks_{subj["id"]}','').strip()
            if v:
                conn.execute("""INSERT INTO marks (student_id,subject_id,marks_obtained) VALUES (?,?,?)
                    ON CONFLICT(student_id,subject_id) DO UPDATE SET marks_obtained=excluded.marks_obtained""",
                             (sid, subj['id'], float(v)))
        conn.commit(); conn.close(); flash('Marks saved!', 'success'); return redirect(f'/teacher/result/{sid}')
    existing = {r['subject_id']:r['marks_obtained'] for r in
                conn.execute("SELECT subject_id,marks_obtained FROM marks WHERE student_id=?", (sid,)).fetchall()}
    conn.close()
    return render_template('enter_marks.html', student=student, subjects=subjects,
                           existing=existing, college=COLLEGE_NAME)

@app.route('/teacher/result/<int:sid>')
@role_required('teacher')
def teacher_view_result(sid):
    data = get_result(sid)
    return render_template('result_view.html', **data, is_teacher=True,
                           college=COLLEGE_NAME, college_short=COLLEGE_SHORT)

@app.route('/teacher/all_results')
@role_required('teacher')
def teacher_all_results():
    conn = get_db()
    students = conn.execute("SELECT * FROM students ORDER BY branch,semester,name").fetchall()
    # Subject toppers
    subjects = conn.execute("SELECT * FROM subjects ORDER BY branch,semester,name").fetchall()
    toppers = []
    for subj in subjects:
        top = conn.execute("""SELECT st.name, st.roll_number, m.marks_obtained, s.max_marks
            FROM marks m JOIN students st ON m.student_id=st.id JOIN subjects s ON m.subject_id=s.id
            WHERE m.subject_id=? ORDER BY m.marks_obtained DESC LIMIT 1""", (subj['id'],)).fetchone()
        if top:
            toppers.append({'subject':subj['name'],'code':subj['code'],'branch':subj['branch'],
                            'semester':subj['semester'],'student_name':top['name'],
                            'roll':top['roll_number'],'marks':top['marks_obtained'],'max':top['max_marks']})
    summaries = []
    grade_counts = {'Distinction':0,'First Class':0,'Pass Class':0,'Fail':0}
    for s in students:
        d = get_result(s['id'])
        summaries.append(dict(id=s['id'],name=s['name'],roll=s['roll_number'],branch=s['branch'],
                              semester=s['semester'],**{k:d[k] for k in ['overall_percentage','overall_grade','grade_color']}))
        if d['overall_grade'] in grade_counts: grade_counts[d['overall_grade']] += 1
    conn.close()
    return render_template('teacher_results.html', summaries=summaries, toppers=toppers,
                           grade_counts=grade_counts, college=COLLEGE_NAME, college_short=COLLEGE_SHORT)

@app.route('/teacher/download_pdf/<int:sid>')
@role_required('teacher')
def teacher_download_pdf(sid): return generate_pdf(sid)

# ── Notices (Teacher) ──
@app.route('/teacher/notices')
@role_required('teacher')
def teacher_notices():
    conn = get_db()
    notices = conn.execute("SELECT * FROM notices ORDER BY id DESC").fetchall()
    conn.close()
    return render_template('teacher_notices.html', notices=notices, college=COLLEGE_NAME)

@app.route('/teacher/add_notice', methods=['POST'])
@role_required('teacher')
def teacher_add_notice():
    now = datetime.now().strftime('%d %b %Y, %I:%M %p')
    conn = get_db()
    conn.execute("INSERT INTO notices (title,content,posted_by,role,created_at) VALUES (?,?,?,?,?)",
                 (request.form['title'].strip(), request.form['content'].strip(),
                  session['user_name'], 'teacher', now))
    conn.commit(); conn.close()
    flash('Notice posted!', 'success'); return redirect('/teacher/notices')

@app.route('/teacher/edit_notice/<int:nid>', methods=['GET','POST'])
@role_required('teacher')
def teacher_edit_notice(nid):
    conn = get_db()
    if request.method == 'POST':
        now = datetime.now().strftime('%d %b %Y, %I:%M %p')
        conn.execute("UPDATE notices SET title=?,content=?,updated_at=? WHERE id=?",
                     (request.form['title'], request.form['content'], now, nid))
        conn.commit(); conn.close(); flash('Notice updated!', 'success'); return redirect('/teacher/notices')
    n = conn.execute("SELECT * FROM notices WHERE id=?", (nid,)).fetchone(); conn.close()
    return render_template('edit_notice.html', notice=n, college=COLLEGE_NAME, back_url='/teacher/notices')

@app.route('/teacher/delete_notice/<int:nid>', methods=['POST'])
@role_required('teacher')
def teacher_delete_notice(nid):
    conn = get_db()
    conn.execute("DELETE FROM notices WHERE id=?", (nid,)); conn.commit(); conn.close()
    flash('Notice deleted.', 'success'); return redirect('/teacher/notices')

# ── Subjects (Teacher) ──
@app.route('/teacher/subjects')
@role_required('teacher')
def manage_subjects():
    conn = get_db()
    subjects = conn.execute("SELECT * FROM subjects ORDER BY branch,semester,name").fetchall()
    conn.close()
    return render_template('manage_subjects.html', subjects=subjects, college=COLLEGE_NAME)

@app.route('/teacher/add_subject', methods=['POST'])
@role_required('teacher')
def add_subject():
    conn = get_db()
    conn.execute("INSERT INTO subjects (name,code,max_marks,semester,branch) VALUES (?,?,?,?,?)",
                 (request.form['name'].strip(), request.form['code'].strip().upper(),
                  int(request.form.get('max_marks',100)), int(request.form['semester']), request.form['branch']))
    conn.commit(); conn.close()
    flash(f"Subject '{request.form['name']}' added!", 'success'); return redirect('/teacher/subjects')

@app.route('/teacher/delete_subject/<int:subj_id>', methods=['POST'])
@role_required('teacher')
def delete_subject(subj_id):
    conn = get_db()
    s = conn.execute("SELECT name FROM subjects WHERE id=?", (subj_id,)).fetchone()
    conn.execute("DELETE FROM marks WHERE subject_id=?", (subj_id,))
    conn.execute("DELETE FROM subjects WHERE id=?", (subj_id,)); conn.commit(); conn.close()
    flash(f"Subject '{s['name']}' removed.", 'success'); return redirect('/teacher/subjects')

# ═══════════════════════════════════════════════════════════════════════════════
# STUDENT ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/student/dashboard')
@role_required('student')
def student_dashboard():
    data = get_result(session['user_id'])
    conn = get_db()
    notices = conn.execute("SELECT * FROM notices ORDER BY id DESC").fetchall()
    conn.close()
    return render_template('student_dashboard.html', **data, notices=notices,
                           college=COLLEGE_NAME, college_short=COLLEGE_SHORT)

@app.route('/student/download_pdf')
@role_required('student')
def student_download_pdf(): return generate_pdf(session['user_id'])

# ─── PDF ──────────────────────────────────────────────────────────────────────

def generate_pdf(sid):
    d = get_result(sid); student = d['student']
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=0.6*inch, bottomMargin=0.6*inch,
                            leftMargin=0.7*inch, rightMargin=0.7*inch)
    els = []
    def ps(name, **kw): return ParagraphStyle(name, **kw)
    els.append(Paragraph(COLLEGE_NAME, ps('t', fontSize=15, fontName='Helvetica-Bold', spaceAfter=3, alignment=1, textColor=colors.HexColor('#0f1b35'))))
    els.append(Paragraph("Academic Result Report Card", ps('s', fontSize=10, fontName='Helvetica', spaceAfter=2, alignment=1, textColor=colors.HexColor('#555'))))
    els.append(Spacer(1,0.1*inch))
    info = Table([['Student Name:', student['name'], 'Roll No:', student['roll_number']],
                  ['Branch:', student['branch'], 'Semester:', f"Sem {student['semester']}"],
                  ['Academic Year:', student['academic_year'], 'Institution:', COLLEGE_SHORT]],
                 colWidths=[1.3*inch,2.3*inch,1.2*inch,2.4*inch])
    info.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),'Helvetica'),('FONTNAME',(0,0),(0,-1),'Helvetica-Bold'),
        ('FONTNAME',(2,0),(2,-1),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),10),
        ('ROWBACKGROUNDS',(0,0),(-1,-1),[colors.HexColor('#e8eeff'),colors.HexColor('#f4f7ff')]),
        ('GRID',(0,0),(-1,-1),0.5,colors.HexColor('#cccccc')),('PADDING',(0,0),(-1,-1),7)]))
    els += [info, Spacer(1,0.15*inch)]
    els.append(Paragraph("Subject-wise Marks", ps('h2', fontSize=12, fontName='Helvetica-Bold', spaceAfter=5, textColor=colors.HexColor('#0f1b35'))))
    mdata = [['Subject','Code','Max Marks','Obtained','Percentage','Result']]
    for r in d['results']:
        mdata.append([r['subject'],r['code'],str(r['max']),str(r['obtained']),f"{r['percentage']}%",r['grade']])
    mt = Table(mdata, colWidths=[2.1*inch,0.9*inch,0.9*inch,0.9*inch,1*inch,1.4*inch])
    mt.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#0f1b35')),
        ('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,-1),9),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f9f9f9')]),
        ('GRID',(0,0),(-1,-1),0.5,colors.HexColor('#dddddd')),('PADDING',(0,0),(-1,-1),6),
        ('ALIGN',(2,0),(-1,-1),'CENTER')]))
    els += [mt, Spacer(1,0.15*inch)]
    gbg = {'Distinction':'#d4edda','First Class':'#cce5ff','Pass Class':'#fff3cd','Fail':'#f8d7da'}.get(d['overall_grade'],'#f8f9fa')
    st = Table([['Total Marks',f"{d['total_obtained']} / {d['total_max']}"],
                ['Overall %',f"{d['overall_percentage']}%"],
                ['Final Result',d['overall_grade']]], colWidths=[3*inch,4.2*inch])
    st.setStyle(TableStyle([('FONTNAME',(0,0),(0,-1),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),11),
        ('BACKGROUND',(0,2),(-1,2),colors.HexColor(gbg)),
        ('GRID',(0,0),(-1,-1),0.5,colors.HexColor('#cccccc')),('PADDING',(0,0),(-1,-1),8)]))
    els += [st, Spacer(1,0.2*inch)]
    els.append(Paragraph("Grade Scale: Distinction ≥75%  |  First Class ≥60%  |  Pass Class ≥40%  |  Fail <40%",
        ps('gs', fontSize=8, alignment=1, textColor=colors.HexColor('#888'))))
    els.append(Spacer(1,0.06*inch))
    els.append(Paragraph(f"Computer-generated result — {COLLEGE_NAME}. No signature required.",
        ps('ft', fontSize=8, alignment=1, textColor=colors.grey)))
    doc.build(els); buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name=f"Result_{student['roll_number']}_{student['name'].replace(' ','_')}.pdf",
                     mimetype='application/pdf')

if __name__ == '__main__':
    init_db()
    print(f"\n{'='*62}")
    print(f"  {COLLEGE_SHORT} — Result Management System v2.0")
    print(f"{'='*62}")
    print("  ✅ Running → http://127.0.0.1:5000")
    print("  Admin   → admin / admin123")
    print("  Teacher → teacher / teacher123")
    print("  Student → CS2024001 / CS2024001")
    print(f"{'='*62}\n")
    app.run(debug=True)
