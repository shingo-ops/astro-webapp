import bcrypt


def hash_password(password: str) -> str:
    """パスワードをbcryptでハッシュ化する。DBにはハッシュのみ保存。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """入力パスワードとDBのハッシュを比較する。元のパスワードを知る必要はない。"""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
