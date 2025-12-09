from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from datetime import datetime, date

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here' # 請更改為隨機字串
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///library.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- 時間設定 ---
# 08:00 到 21:30，共 27 個時段 (每30分鐘一格)
# Index 0 = 08:00, Index 1 = 08:30 ...
TIME_SLOTS = []
start_hour = 8
for i in range(28): # 08:00 到 21:30 需要涵蓋到結束點
    h = start_hour + (i * 30) // 60
    m = (i * 30) % 60
    TIME_SLOTS.append(f"{h:02d}:{m:02d}")

# --- 資料庫模型 ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), unique=True, nullable=False) # 學號
    name = db.Column(db.String(50), nullable=False)
    password = db.Column(db.String(80), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    room_number = db.Column(db.Integer, nullable=False) # 1-6
    booking_date = db.Column(db.Date, nullable=False)
    start_index = db.Column(db.Integer, nullable=False) # 開始的時間塊 index
    duration_slots = db.Column(db.Integer, nullable=False) # 持續幾個 30分鐘
    
    user = db.relationship('User', backref=db.backref('bookings', lazy=True))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- 路由 ---

@app.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    
    # 預設顯示今天的預約狀況，若有參數則顯示選定日期
    query_date_str = request.args.get('date', str(date.today()))
    try:
        query_date = datetime.strptime(query_date_str, '%Y-%m-%d').date()
    except:
        query_date = date.today()

    # 取得當日所有預約
    bookings = Booking.query.filter_by(booking_date=query_date).all()
    
    # 建構 6間討論室 x 27個時段 的狀態矩陣
    # status[room_idx][time_idx] = None or User Name
    room_status = [[None for _ in range(len(TIME_SLOTS)-1)] for _ in range(6)]
    
    for b in bookings:
        # 討論室 1 對應 index 0
        r_idx = b.room_number - 1
        for i in range(b.duration_slots):
            t_idx = b.start_index + i
            if t_idx < len(TIME_SLOTS) - 1:
                room_status[r_idx][t_idx] = b.user.name

    return render_template('index.html', 
                           date=query_date, 
                           time_slots=TIME_SLOTS, 
                           room_status=room_status,
                           today=date.today())

@app.route('/book', methods=['GET', 'POST'])
@login_required
def book():
    if request.method == 'POST':
        booking_date_str = request.form.get('date')
        room = int(request.form.get('room'))
        start_time_idx = int(request.form.get('start_time'))
        duration = int(request.form.get('duration')) # 1=30m, 2=60m...

        booking_date = datetime.strptime(booking_date_str, '%Y-%m-%d').date()
        
        # 檢查衝突
        # 新預約區間: [start, start + duration)
        existing_bookings = Booking.query.filter_by(booking_date=booking_date, room_number=room).all()
        
        is_conflict = False
        new_start = start_time_idx
        new_end = start_time_idx + duration

        for b in existing_bookings:
            b_start = b.start_index
            b_end = b.start_index + b.duration_slots
            # 判斷區間重疊
            if max(new_start, b_start) < min(new_end, b_end):
                is_conflict = True
                break
        
        if is_conflict:
            flash('該時段已被預約，請選擇其他時間或討論室。', 'danger')
        else:
            new_booking = Booking(
                user_id=current_user.id,
                room_number=room,
                booking_date=booking_date,
                start_index=start_time_idx,
                duration_slots=duration
            )
            db.session.add(new_booking)
            db.session.commit()
            flash('預約成功！', 'success')
            return redirect(url_for('index', date=booking_date_str))

    return render_template('book.html', time_slots=TIME_SLOTS, today=date.today())

@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        flash('權限不足', 'danger')
        return redirect(url_for('index'))
    
    all_bookings = Booking.query.order_by(Booking.booking_date.desc(), Booking.start_index).all()
    return render_template('admin.html', bookings=all_bookings, time_slots=TIME_SLOTS)

@app.route('/admin/delete/<int:id>')
@login_required
def delete_booking(id):
    if not current_user.is_admin:
        return redirect(url_for('index'))
    
    booking = Booking.query.get_or_404(id)
    db.session.delete(booking)
    db.session.commit()
    flash('預約已刪除', 'info')
    return redirect(url_for('admin'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        student_id = request.form.get('student_id')
        password = request.form.get('password')
        user = User.query.filter_by(student_id=student_id).first()
        
        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash('登入失敗，請檢查學號或密碼', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        student_id = request.form.get('student_id')
        name = request.form.get('name')
        password = request.form.get('password')
        
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        
        # 簡單邏輯：如果是第一個註冊的人，自動變成管理員 (方便你測試)
        is_admin = False
        if User.query.count() == 0:
            is_admin = True
            
        new_user = User(student_id=student_id, name=name, password=hashed_password, is_admin=is_admin)
        
        try:
            db.session.add(new_user)
            db.session.commit()
            flash('註冊成功，請登入', 'success')
            return redirect(url_for('login'))
        except:
            flash('該學號已被註冊', 'danger')
            
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)