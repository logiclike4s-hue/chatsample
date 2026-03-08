from flask import Flask, render_template, request, session, redirect, url_for, jsonify, send_file
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import json
import uuid
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chat.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = 3600

# Настройки для загрузки файлов
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mp3', 'doc', 'docx', 'xls', 'xlsx', 'zip',
                      'rar'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Создаем папку для загрузок, если её нет
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")


# Модель пользователя
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    is_online = db.Column(db.Boolean, default=False)
    current_room = db.Column(db.String(50), default='')
    total_messages = db.Column(db.Integer, default=0)
    total_time_online = db.Column(db.Integer, default=0)


# Модель сообщения
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50))
    text = db.Column(db.String(500), nullable=True)
    room = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    message_type = db.Column(db.String(20), default='text')  # text, image, file, video, audio
    file_name = db.Column(db.String(255), nullable=True)
    file_path = db.Column(db.String(255), nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    file_type = db.Column(db.String(50), nullable=True)
    reactions = db.relationship('Reaction', backref='message', lazy=True, cascade='all, delete-orphan')


# Модель реакции
class Reaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'))
    username = db.Column(db.String(50))
    emoji = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('message_id', 'username', 'emoji', name='unique_reaction'),)


# Модель комнаты
class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    display_name = db.Column(db.String(50))
    emoji = db.Column(db.String(10), default='💬')
    description = db.Column(db.String(200))
    topic = db.Column(db.String(200), default='')
    created_by = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            'name': self.name,
            'display_name': self.display_name or self.name.capitalize(),
            'emoji': self.emoji,
            'description': self.description,
            'topic': self.topic,
            'created_by': self.created_by
        }


# Модель для отслеживания участников
class RoomParticipant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50))
    room = db.Column(db.String(50))
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_activity = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('username', 'room', name='unique_user_room'),)


# Создаем таблицы
with app.app_context():
    db.create_all()
    print("✅ База данных создана!")


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_file_type(filename):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    image_ext = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'}
    video_ext = {'mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv'}
    audio_ext = {'mp3', 'wav', 'ogg', 'flac', 'aac'}
    if ext in image_ext:
        return 'image'
    elif ext in video_ext:
        return 'video'
    elif ext in audio_ext:
        return 'audio'
    else:
        return 'file'


@app.route("/")
def index():
    if 'username' in session:
        return redirect(url_for('chat'))
    return redirect(url_for('login'))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            session['username'] = username
            session.permanent = True
            user.is_online = True
            user.last_seen = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('chat'))
        else:
            return render_template("login.html", error="Неверное имя или пароль")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return render_template("register.html", error="Пользователь уже существует")
        new_user = User(username=username, password=password, is_online=True)
        db.session.add(new_user)
        db.session.commit()
        session['username'] = username
        session.permanent = True
        return redirect(url_for('chat'))
    return render_template("register.html")


@app.route("/chat")
def chat():
    if 'username' not in session:
        return redirect(url_for('login'))
    rooms = Room.query.filter_by(is_active=True).all()
    room_users = {}
    for room in rooms:
        count = RoomParticipant.query.filter_by(room=room.name).count()
        room_users[room.name] = count
    room_messages = {}
    for room in rooms:
        messages = Message.query.filter_by(room=room.name).order_by(Message.timestamp.desc()).limit(50).all()
        for msg in messages:
            msg.reactions_list = Reaction.query.filter_by(message_id=msg.id).all()
        room_messages[room.name] = list(reversed(messages))
    active_room = request.args.get('room', '')
    if active_room and not Room.query.filter_by(name=active_room).first():
        active_room = ''
    return render_template("chat.html",
                           username=session['username'],
                           rooms=rooms,
                           room_messages=room_messages,
                           room_users=room_users,
                           active_room=active_room)


@app.route("/upload", methods=["POST"])
def upload_file():
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    room = request.form.get('room', 'general')

    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if file and allowed_file(file.filename):
        # Генерируем уникальное имя файла
        original_filename = secure_filename(file.filename)
        file_ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
        unique_filename = f"{uuid.uuid4().hex}_{original_filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)

        # Сохраняем файл
        file.save(file_path)
        file_size = os.path.getsize(file_path)
        file_type = get_file_type(original_filename)

        # Создаем сообщение о файле
        msg = Message(
            username=session['username'],
            text=f"📎 {original_filename}",
            room=room,
            message_type=file_type,
            file_name=original_filename,
            file_path=unique_filename,
            file_size=file_size,
            file_type=file_ext
        )
        db.session.add(msg)

        # Обновляем счетчик сообщений пользователя
        user = User.query.filter_by(username=session['username']).first()
        if user:
            user.total_messages += 1

        db.session.commit()

        # Отправляем сообщение через socketio
        socketio.emit('receive_message', {
            'id': msg.id,
            'username': session['username'],
            'message': f"📎 {original_filename}",
            'room': room,
            'time': datetime.now().strftime('%H:%M'),
            'message_type': file_type,
            'file_name': original_filename,
            'file_path': unique_filename,
            'file_size': file_size,
            'file_ext': file_ext,
            'reactions': {}
        }, room=room)

        return jsonify({
            'success': True,
            'message': 'File uploaded successfully',
            'file_name': original_filename,
            'file_path': unique_filename,
            'file_size': file_size,
            'file_type': file_type
        })

    return jsonify({'error': 'File type not allowed'}), 400


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename))


@app.route("/api/rooms", methods=["GET"])
def get_rooms():
    rooms = Room.query.filter_by(is_active=True).all()
    return jsonify([room.to_dict() for room in rooms])


@app.route("/api/rooms", methods=["POST"])
def create_room():
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    room_name = data.get('name', '').lower().replace(' ', '-')

    if not room_name:
        return jsonify({'error': 'Room name cannot be empty'}), 400

    # Проверяем, существует ли уже такая комната
    existing = Room.query.filter_by(name=room_name).first()
    if existing:
        return jsonify({'error': 'Room already exists'}), 400

    # Создаем новую комнату
    new_room = Room(
        name=room_name,
        display_name=data.get('display_name', room_name.capitalize()),
        emoji=data.get('emoji', '💬'),
        description=data.get('description', ''),
        topic=data.get('topic', ''),
        created_by=session['username']
    )

    db.session.add(new_room)
    db.session.commit()

    # Оповещаем всех о новой комнате
    socketio.emit('room_created', new_room.to_dict())

    return jsonify({'success': True, 'room': new_room.to_dict()})


@app.route("/api/room/<room_name>", methods=["PUT"])
def update_room(room_name):
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    data = request.json
    room = Room.query.filter_by(name=room_name).first()
    if not room:
        return jsonify({'error': 'Room not found'}), 404
    if 'name' in data and data['name']:
        new_name = data['name'].lower().replace(' ', '-')
        if new_name != room_name and Room.query.filter_by(name=new_name).first():
            return jsonify({'error': 'Name already exists'}), 400
        room.name = new_name
        room.display_name = data.get('display_name', new_name.capitalize())
    if 'emoji' in data:
        room.emoji = data['emoji']
    if 'description' in data:
        room.description = data['description']
    if 'topic' in data:
        room.topic = data['topic']
    db.session.commit()
    socketio.emit('room_updated', {'old_name': room_name, 'room': room.to_dict()})
    return jsonify({'success': True, 'room': room.to_dict()})


@app.route("/api/room/<room_name>", methods=["DELETE"])
def delete_room(room_name):
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    room = Room.query.filter_by(name=room_name).first()
    if not room:
        return jsonify({'error': 'Room not found'}), 404
    Message.query.filter_by(room=room_name).delete()
    RoomParticipant.query.filter_by(room=room_name).delete()
    db.session.delete(room)
    db.session.commit()
    socketio.emit('room_deleted', {'name': room_name})
    return jsonify({'success': True})


@app.route("/api/stats")
def get_stats():
    total_users = User.query.count()
    online_users = User.query.filter_by(is_online=True).count()
    total_messages = Message.query.count()
    total_rooms = Room.query.filter_by(is_active=True).count()

    recent_messages = Message.query.order_by(Message.timestamp.desc()).limit(20).all()
    messages_list = []
    for msg in recent_messages:
        messages_list.append({
            'id': msg.id,
            'username': msg.username,
            'text': msg.text,
            'room': msg.room,
            'time': msg.timestamp.strftime('%H:%M'),
            'date': msg.timestamp.strftime('%Y-%m-%d'),
            'message_type': msg.message_type,
            'file_name': msg.file_name
        })

    return jsonify({
        'total_users': total_users,
        'online_users': online_users,
        'total_messages': total_messages,
        'total_rooms': total_rooms,
        'recent_messages': messages_list
    })


@app.route("/logout")
def logout():
    if 'username' in session:
        username = session['username']
        RoomParticipant.query.filter_by(username=username).delete()
        user = User.query.filter_by(username=username).first()
        if user:
            user.is_online = False
            user.last_seen = datetime.utcnow()
        db.session.commit()
        socketio.emit('user_offline', {'username': username})
    session.pop('username', None)
    return redirect(url_for('login'))


@socketio.on('join')
def handle_join(data):
    username = session.get('username')
    if not username:
        return
    room = data['room']
    room_exists = Room.query.filter_by(name=room).first()
    if not room_exists:
        return
    existing = RoomParticipant.query.filter_by(username=username, room=room).first()
    if not existing:
        participant = RoomParticipant(username=username, room=room)
        db.session.add(participant)
        db.session.commit()
        users_count = RoomParticipant.query.filter_by(room=room).count()
        join_room(room)
        emit('user_joined', {
            'username': username,
            'room': room,
            'users_count': users_count,
            'joined_at': participant.joined_at.timestamp() * 1000
        }, room=room)


@socketio.on('leave')
def handle_leave(data):
    username = session.get('username')
    if not username:
        return
    room = data['room']
    participant = RoomParticipant.query.filter_by(username=username, room=room).first()
    if participant:
        time_spent = (datetime.utcnow() - participant.joined_at).seconds
        user = User.query.filter_by(username=username).first()
        if user:
            user.total_time_online += time_spent
        db.session.delete(participant)
        db.session.commit()
        leave_room(room)
        users_count = RoomParticipant.query.filter_by(room=room).count()
        emit('user_left', {
            'username': username,
            'room': room,
            'users_count': users_count
        }, room=room)


@socketio.on('switch_room')
def handle_switch_room(data):
    username = session.get('username')
    if not username:
        return
    old_room = data.get('old_room')
    new_room = data['new_room']

    # Уходим из старой комнаты
    if old_room and old_room != new_room:
        old_participant = RoomParticipant.query.filter_by(username=username, room=old_room).first()
        if old_participant:
            time_spent = (datetime.utcnow() - old_participant.joined_at).seconds
            user = User.query.filter_by(username=username).first()
            if user:
                user.total_time_online += time_spent
            db.session.delete(old_participant)
            db.session.commit()
            leave_room(old_room)
            old_count = RoomParticipant.query.filter_by(room=old_room).count()
            emit('user_left', {
                'username': username,
                'room': old_room,
                'users_count': old_count
            }, room=old_room)

    # Присоединяемся к новой комнате
    new_participant = RoomParticipant.query.filter_by(username=username, room=new_room).first()
    if not new_participant:
        participant = RoomParticipant(username=username, room=new_room)
        db.session.add(participant)
        db.session.commit()
        join_room(new_room)
        new_count = RoomParticipant.query.filter_by(room=new_room).count()
        emit('user_joined', {
            'username': username,
            'room': new_room,
            'users_count': new_count,
            'joined_at': participant.joined_at.timestamp() * 1000
        }, room=new_room)
    else:
        join_room(new_room)


@socketio.on('send_message')
def handle_message(data):
    username = session.get('username')
    if not username:
        return
    room = data['room']
    message_text = data['message']
    room_exists = Room.query.filter_by(name=room).first()
    if not room_exists:
        return
    msg = Message(username=username, text=message_text, room=room, message_type='text')
    db.session.add(msg)
    user = User.query.filter_by(username=username).first()
    if user:
        user.total_messages += 1
    db.session.commit()
    participant = RoomParticipant.query.filter_by(username=username, room=room).first()
    if participant:
        participant.last_activity = datetime.utcnow()
        db.session.commit()
    emit('receive_message', {
        'id': msg.id,
        'username': username,
        'message': message_text,
        'room': room,
        'time': datetime.now().strftime('%H:%M'),
        'message_type': 'text',
        'reactions': {}
    }, room=room)


@socketio.on('add_reaction')
def handle_add_reaction(data):
    username = session.get('username')
    if not username:
        return
    message_id = data['message_id']
    emoji = data['emoji']
    message = Message.query.get(message_id)
    if not message:
        return
    existing = Reaction.query.filter_by(message_id=message_id, username=username, emoji=emoji).first()
    if existing:
        db.session.delete(existing)
    else:
        reaction = Reaction(message_id=message_id, username=username, emoji=emoji)
        db.session.add(reaction)
    db.session.commit()
    reactions = {}
    for r in Reaction.query.filter_by(message_id=message_id).all():
        if r.emoji not in reactions:
            reactions[r.emoji] = []
        reactions[r.emoji].append(r.username)
    emit('reaction_update', {
        'message_id': message_id,
        'reactions': reactions
    }, room=message.room)


@socketio.on('connect')
def handle_connect():
    username = session.get('username')
    if username:
        print(f'🟢 Клиент подключился: {username}')
        user = User.query.filter_by(username=username).first()
        if user:
            user.is_online = True
            user.last_seen = datetime.utcnow()
            db.session.commit()


@socketio.on('disconnect')
def handle_disconnect():
    username = session.get('username')
    if username:
        print(f'🔴 Клиент отключился: {username}')
        rooms = RoomParticipant.query.filter_by(username=username).all()
        for room_participant in rooms:
            room_name = room_participant.room
            db.session.delete(room_participant)
            users_count = RoomParticipant.query.filter_by(room=room_name).count()
            emit('user_left', {
                'username': username,
                'room': room_name,
                'users_count': users_count
            }, room=room_name)
        db.session.commit()
        user = User.query.filter_by(username=username).first()
        if user:
            user.is_online = False
            user.last_seen = datetime.utcnow()
            db.session.commit()


@socketio.on('typing')
def handle_typing(data):
    username = session.get('username')
    if not username:
        return
    emit('typing', {'username': username, 'room': data['room']}, room=data['room'])


@socketio.on('stop_typing')
def handle_stop_typing(data):
    username = session.get('username')
    if not username:
        return
    emit('stop_typing', {'username': username, 'room': data['room']}, room=data['room'])


if __name__ == "__main__":
    print("=" * 50)
    print("🚀 ЗАПУСК СЕРВЕРА")
    print("=" * 50)

    # Пробуем разные порты
    ports_to_try = [5001, 5002, 5003, 8080, 3000]

    for port in ports_to_try:
        try:
            print(f"Пробуем порт {port}...")
            socketio.run(app, host="127.0.0.1", port=port, debug=True)
            break
        except OSError:
            print(f"❌ Порт {port} занят, пробуем следующий...")
            continue