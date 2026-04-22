from flask import (
    Flask, request, jsonify, render_template,
    send_from_directory, abort, Response
)
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token,
    jwt_required, get_jwt_identity, verify_jwt_in_request
)
from datetime import timedelta, datetime
from werkzeug.utils import secure_filename
import os, uuid, mimetypes

app = Flask(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_VIDEO = {"mp4", "webm", "ogg", "mov", "avi", "mkv"}
ALLOWED_IMAGE = {"jpg", "jpeg", "png", "gif", "webp"}
MAX_VIDEO_MB  = 500

# PostgreSQL connection — change YOUR_PASSWORD to your postgres password
DB_USER     = os.environ.get("DB_USER",     "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "9909")
DB_HOST     = os.environ.get("DB_HOST",     "localhost")
DB_PORT     = os.environ.get("DB_PORT",     "5432")
DB_NAME     = os.environ.get("DB_NAME",     "streamvault")

app.config["SQLALCHEMY_DATABASE_URI"] = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"]           = "streamvault-secret-change-in-prod"
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)
app.config["MAX_CONTENT_LENGTH"]       = MAX_VIDEO_MB * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db     = SQLAlchemy(app)
bcrypt = Bcrypt(app)
jwt    = JWTManager(app)
@jwt.unauthorized_loader
def unauthorized_callback(err):
    return jsonify({"error": "Missing Authorization Header"}), 401

@jwt.invalid_token_loader
def invalid_token_callback(err):
    return jsonify({"error": "Invalid token"}), 422

@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    return jsonify({"error": "Token has expired"}), 401
CORS(app)

# ── Models ─────────────────────────────────────────────────────────────────────
class User(db.Model):
    __tablename__ = "users"
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80),  unique=True, nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    avatar        = db.Column(db.String(256), nullable=True)
    bio           = db.Column(db.Text, nullable=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    videos        = db.relationship("Video", backref="uploader", lazy=True)

    def set_password(self, p):  self.password_hash = bcrypt.generate_password_hash(p).decode()
    def check_password(self, p): return bcrypt.check_password_hash(self.password_hash, p)
    def to_dict(self, viewer_id=None):
        sub_count = Subscription.query.filter_by(channel_id=self.id).count()
        is_subscribed = False
        if viewer_id:
            is_subscribed = bool(Subscription.query.filter_by(
                subscriber_id=viewer_id, channel_id=self.id).first())
        return {
            "id": self.id, "username": self.username, "email": self.email,
            "avatar": self.avatar, "bio": self.bio,
            "video_count": len(self.videos),
            "subscriber_count": sub_count,
            "is_subscribed": is_subscribed,
            "created_at": self.created_at.isoformat()
        }


class Video(db.Model):
    __tablename__ = "videos"
    id          = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title       = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    filename    = db.Column(db.String(256), nullable=False)
    thumbnail   = db.Column(db.String(256), nullable=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    views       = db.Column(db.Integer, default=0)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self, include_uploader=True, user_id=None):
        likes    = Like.query.filter_by(video_id=self.id, is_like=True).count()
        dislikes = Like.query.filter_by(video_id=self.id, is_like=False).count()
        user_reaction = None
        if user_id:
            existing = Like.query.filter_by(video_id=self.id, user_id=user_id).first()
            if existing:
                user_reaction = "like" if existing.is_like else "dislike"
        d = {
            "id": self.id, "title": self.title, "description": self.description,
            "thumbnail": f"/uploads/{self.thumbnail}" if self.thumbnail else None,
            "video_url": f"/stream/{self.id}",
            "views": self.views, "created_at": self.created_at.isoformat(),
            "user_id": self.user_id,
            "likes": likes, "dislikes": dislikes, "user_reaction": user_reaction,
        }
        if include_uploader and self.uploader:
            d["uploader"] = {"id": self.uploader.id, "username": self.uploader.username, "avatar": self.uploader.avatar}
        return d




class Like(db.Model):
    __tablename__ = "likes"
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    video_id   = db.Column(db.String(36), db.ForeignKey("videos.id"), nullable=False)
    is_like    = db.Column(db.Boolean, nullable=False)  # True = like, False = dislike
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("user_id", "video_id", name="unique_user_video_like"),)


class Subscription(db.Model):
    __tablename__ = "subscriptions"
    id            = db.Column(db.Integer, primary_key=True)
    subscriber_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    channel_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("subscriber_id", "channel_id", name="unique_subscription"),)

# ── Helpers ────────────────────────────────────────────────────────────────────
def allowed_file(filename, allowed):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed

def current_user_id():
    try:
        verify_jwt_in_request()
        return get_jwt_identity()
    except Exception:
        return None

def time_ago(dt):
    diff = datetime.utcnow() - dt
    s = diff.total_seconds()
    if s < 60:    return "just now"
    if s < 3600:  return f"{int(s//60)}m ago"
    if s < 86400: return f"{int(s//3600)}h ago"
    if s < 604800: return f"{int(s//86400)}d ago"
    return dt.strftime("%b %d, %Y")


# ── Page Routes ────────────────────────────────────────────────────────────────
@app.route("/")
def index():    return render_template("login.html")

@app.route("/home")
def home():     return render_template("index.html")

@app.route("/watch/<video_id>")
def watch(video_id): return render_template("watch.html")

@app.route("/channel/<username>")
def channel(username): return render_template("channel.html")

@app.route("/upload")
def upload_page(): return render_template("upload.html")

@app.route("/search")
def search_page(): return render_template("search.html")


# ── File serving ───────────────────────────────────────────────────────────────
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route("/stream/<video_id>")
def stream_video(video_id):
    video = Video.query.get_or_404(video_id)
    path  = os.path.join(UPLOAD_FOLDER, video.filename)
    if not os.path.exists(path):
        abort(404)

    file_size = os.path.getsize(path)
    range_hdr = request.headers.get("Range")
    mime      = mimetypes.guess_type(path)[0] or "video/mp4"

    if range_hdr:
        start, end = 0, file_size - 1
        parts = range_hdr.replace("bytes=", "").split("-")
        start = int(parts[0])
        if parts[1]: end = int(parts[1])
        chunk = min(1024 * 1024, end - start + 1)
        end   = start + chunk - 1

        def gen():
            with open(path, "rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining:
                    data = f.read(min(65536, remaining))
                    if not data: break
                    yield data
                    remaining -= len(data)

        return Response(gen(), 206, {
            "Content-Range":  f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges":  "bytes",
            "Content-Length": str(end - start + 1),
            "Content-Type":   mime,
        })

    return send_from_directory(UPLOAD_FOLDER, video.filename, mimetype=mime)


# ── Auth API ───────────────────────────────────────────────────────────────────
@app.route("/api/signup", methods=["POST"])
def signup():
    d = request.get_json()
    username = (d.get("username") or "").strip()
    email    = (d.get("email")    or "").strip().lower()
    password =  d.get("password") or ""
    if not username or not email or not password:
        return jsonify({"error": "All fields are required."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Username already taken."}), 409
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered."}), 409
    user = User(username=username, email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    token = create_access_token(identity=str(user.id))
    return jsonify({"message": "Account created!", "token": token, "user": user.to_dict()}), 201

@app.route("/api/login", methods=["POST"])
def login():
    d          = request.get_json()
    identifier = (d.get("identifier") or "").strip()
    password   =  d.get("password")   or ""
    if not identifier or not password:
        return jsonify({"error": "All fields required."}), 400
    user = User.query.filter_by(username=identifier).first() or \
           User.query.filter_by(email=identifier.lower()).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid credentials."}), 401
    token = create_access_token(identity=str(user.id))
    return jsonify({"message": f"Welcome back, {user.username}!", "token": token, "user": user.to_dict()}), 200

@app.route("/api/me", methods=["GET"])
@jwt_required()
def me():
    print('here')
    user_id = int(get_jwt_identity())
    print('user_id',user_id)
    user = User.query.get(user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({"user": user.to_dict()}), 200

# ── Video API ──────────────────────────────────────────────────────────────────
@app.route("/api/videos", methods=["GET"])
def list_videos():
    page  = request.args.get("page",  1, type=int)
    limit = request.args.get("limit", 12, type=int)
    q     = request.args.get("q",     "", type=str).strip()

    query = Video.query
    if q:
        query = query.filter(
            Video.title.ilike(f"%{q}%") | Video.description.ilike(f"%{q}%")
        )
    total  = query.count()
    videos = query.order_by(Video.created_at.desc()).offset((page-1)*limit).limit(limit).all()
    return jsonify({
        "videos": [v.to_dict() for v in videos],
        "total": total, "page": page, "pages": (total + limit - 1) // limit
    })

@app.route("/api/videos/upload", methods=["POST"])
@jwt_required()
def upload_video():
    uid = int(get_jwt_identity())
    if "video" not in request.files:
        return jsonify({"error": "No video file provided."}), 400

    file  = request.files["video"]
    title = (request.form.get("title") or "").strip()
    desc  = (request.form.get("description") or "").strip()

    if not file.filename or not allowed_file(file.filename, ALLOWED_VIDEO):
        return jsonify({"error": "Invalid video format. Use mp4, webm, ogg, mov."}), 400
    if not title:
        return jsonify({"error": "Title is required."}), 400

    ext      = file.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4()}.{ext}"
    file.save(os.path.join(UPLOAD_FOLDER, filename))

    thumb_name = None
    if "thumbnail" in request.files:
        thumb = request.files["thumbnail"]
        if thumb.filename and allowed_file(thumb.filename, ALLOWED_IMAGE):
            t_ext      = thumb.filename.rsplit(".", 1)[1].lower()
            thumb_name = f"thumb_{uuid.uuid4()}.{t_ext}"
            thumb.save(os.path.join(UPLOAD_FOLDER, thumb_name))

    video = Video(title=title, description=desc, filename=filename,
                  thumbnail=thumb_name, user_id=uid)
    db.session.add(video)
    db.session.commit()
    return jsonify({"message": "Video uploaded!", "video": video.to_dict()}), 201

@app.route("/api/videos/<video_id>", methods=["GET"])
def get_video(video_id):
    video = Video.query.get_or_404(video_id)
    video.views += 1
    db.session.commit()
    uid = None
    try:
        from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity: uid = int(identity)
    except: pass
    return jsonify({"video": video.to_dict(user_id=uid)})

@app.route("/api/videos/<video_id>/like", methods=["POST"])
@jwt_required()
def like_video(video_id):
    uid      = int(get_jwt_identity())
    data     = request.get_json() or {}
    is_like  = data.get("is_like")  # True = like, False = dislike
    if is_like is None:
        return jsonify({"error": "is_like field required (true or false)"}), 400
    video = Video.query.get_or_404(video_id)
    existing = Like.query.filter_by(user_id=uid, video_id=video_id).first()
    if existing:
        if existing.is_like == is_like:
            # clicking same button again = remove reaction
            db.session.delete(existing)
            db.session.commit()
            return jsonify({"message": "Reaction removed", "user_reaction": None,
                            "likes": Like.query.filter_by(video_id=video_id, is_like=True).count(),
                            "dislikes": Like.query.filter_by(video_id=video_id, is_like=False).count()})
        else:
            # switch reaction
            existing.is_like = is_like
    else:
        db.session.add(Like(user_id=uid, video_id=video_id, is_like=is_like))
    db.session.commit()
    return jsonify({"message": "ok", "user_reaction": "like" if is_like else "dislike",
                    "likes": Like.query.filter_by(video_id=video_id, is_like=True).count(),
                    "dislikes": Like.query.filter_by(video_id=video_id, is_like=False).count()})

@app.route("/api/videos/<video_id>", methods=["DELETE"])
@jwt_required()
def delete_video(video_id):
    uid   = int(get_jwt_identity())
    video = Video.query.get_or_404(video_id)
    if video.user_id != uid:
        return jsonify({"error": "Unauthorized."}), 403
    try: os.remove(os.path.join(UPLOAD_FOLDER, video.filename))
    except: pass
    if video.thumbnail:
        try: os.remove(os.path.join(UPLOAD_FOLDER, video.thumbnail))
        except: pass
    db.session.delete(video)
    db.session.commit()
    return jsonify({"message": "Video deleted."})

@app.route("/api/channel/<username>", methods=["GET"])
def get_channel(username):
    user   = User.query.filter_by(username=username).first_or_404()
    videos = Video.query.filter_by(user_id=user.id).order_by(Video.created_at.desc()).all()
    viewer_id = None
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity: viewer_id = int(identity)
    except: pass
    return jsonify({"user": user.to_dict(viewer_id=viewer_id),
                    "videos": [v.to_dict(include_uploader=False) for v in videos]})

@app.route("/api/channel/<username>/subscribe", methods=["POST"])
@jwt_required()
def toggle_subscribe(username):
    uid     = int(get_jwt_identity())
    channel = User.query.filter_by(username=username).first_or_404()
    if channel.id == uid:
        return jsonify({"error": "You cannot subscribe to your own channel."}), 400
    existing = Subscription.query.filter_by(subscriber_id=uid, channel_id=channel.id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({"subscribed": False,
                        "subscriber_count": Subscription.query.filter_by(channel_id=channel.id).count()})
    db.session.add(Subscription(subscriber_id=uid, channel_id=channel.id))
    db.session.commit()
    return jsonify({"subscribed": True,
                    "subscriber_count": Subscription.query.filter_by(channel_id=channel.id).count()})

@app.route("/api/subscriptions/feed", methods=["GET"])
@jwt_required()
def subscription_feed():
    uid  = int(get_jwt_identity())
    subs = Subscription.query.filter_by(subscriber_id=uid).all()
    channel_ids = [s.channel_id for s in subs]
    if not channel_ids:
        return jsonify({"videos": []})
    videos = Video.query.filter(Video.user_id.in_(channel_ids))                        .order_by(Video.created_at.desc()).limit(24).all()
    return jsonify({"videos": [v.to_dict() for v in videos]})


# ── Boot ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        print("✓ StreamVault DB ready.")
    app.run(debug=True, port=5000)
