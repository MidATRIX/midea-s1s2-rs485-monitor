import sqlite3
import os
import datetime
from src.config import SQLITE_DB_DIR

# Root directory for shared telemetry
DB_DIR = SQLITE_DB_DIR
os.makedirs(DB_DIR, exist_ok=True)

_conn = None
_current_db_date = None
_frame_count = 0

def get_db_path():
    """Generates path based on current date: telemetry_2026_02_21.db"""
    date_str = datetime.datetime.now().strftime("%Y_%m_%d")
    return os.path.join(DB_DIR, f"telemetry_{date_str}.db")

def update_latest_symlink(target_path):
    """Updates latest.db to point to today's file for Grafana"""
    symlink_path = os.path.join(DB_DIR, "latest.db")
    try:
        if os.path.lexists(symlink_path):
            os.remove(symlink_path)
        os.symlink(target_path, symlink_path)
    except Exception as e:
        print(f"Symlink error: {e}")

def init_db(path):
    """Initializes a specific database file"""
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scomms_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT (datetime('now', 'localtime')),
            frame1 TEXT,
            IDU5 INTEGER, IDU6 INTEGER, IDU7 INTEGER, IDU8 INTEGER,
            IDU9 INTEGER, IDU10 INTEGER, IDU11 INTEGER, IDU12 INTEGER,
            IDU13 INTEGER, IDU14 INTEGER, IDU15 INTEGER, IDU16 INTEGER,
            IDU17 INTEGER,
            frame2 TEXT,
            ODU5 INTEGER, ODU6 INTEGER, ODU7 INTEGER, ODU8 INTEGER,
            ODU9 INTEGER, ODU10 INTEGER, ODU11 INTEGER, ODU12 INTEGER,
            ODU13 INTEGER, ODU14 INTEGER, ODU15 INTEGER, ODU16 INTEGER,
            ODU17 INTEGER,
            frame3 TEXT,
            HPA5 INTEGER, HPA6 INTEGER, HPA7 INTEGER, HPA8 INTEGER,
            HPA9 INTEGER, HPA10 INTEGER, HPA11 INTEGER, HPA12 INTEGER,
            HPA13 INTEGER, HPA14 INTEGER, HPA15 INTEGER, HPA16 INTEGER,
            HPA17 INTEGER,
            frame4 TEXT,
            HPB5 INTEGER, HPB6 INTEGER, HPB7 INTEGER, HPB8 INTEGER,
            HPB9 INTEGER, HPB10 INTEGER, HPB11 INTEGER, HPB12 INTEGER,
            HPB13 INTEGER, HPB14 INTEGER, HPB15 INTEGER, HPB16 INTEGER,
            HPB17 INTEGER,
            frame5 TEXT,
            HPC5 INTEGER, HPC6 INTEGER, HPC7 INTEGER, HPC8 INTEGER,
            HPC9 INTEGER, HPC10 INTEGER, HPC11 INTEGER, HPC12 INTEGER,
            HPC13 INTEGER, HPC14 INTEGER, HPC15 INTEGER, HPC16 INTEGER,
            HPC17 INTEGER,
            frame6 TEXT,
            HPD5 INTEGER, HPD6 INTEGER, HPD7 INTEGER, HPD8 INTEGER,
            HPD9 INTEGER, HPD10 INTEGER, HPD11 INTEGER, HPD12 INTEGER,
            HPD13 INTEGER, HPD14 INTEGER, HPD15 INTEGER, HPD16 INTEGER,
            HPD17 INTEGER
        )
    ''')
    conn.commit()
    return conn

def save_frame(combined_payload):
    global _conn, _frame_count, _current_db_date
    
    try:
        now = datetime.datetime.now()
        today_date = now.date()

        # Handle Daily Rotation
        if _conn is None or today_date != _current_db_date:
            if _conn:
                _conn.commit()
                _conn.close()
            new_path = get_db_path()
            _conn = init_db(new_path)
            _current_db_date = today_date
            update_latest_symlink(new_path)
            print(f"📂 Active Database: {new_path}")

        cursor = _conn.cursor()
#        ts_string = now.strftime('%Y-%m-%d %H:%M:%S')
        ts_string = now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        columns = [
            "timestamp", 
            "frame1", "IDU5","IDU6","IDU7","IDU8","IDU9","IDU10","IDU11","IDU12","IDU13","IDU14","IDU15","IDU16","IDU17",
            "frame2", "ODU5","ODU6","ODU7","ODU8","ODU9","ODU10","ODU11","ODU12","ODU13","ODU14","ODU15","ODU16","ODU17",
            "frame3", "HPA5","HPA6","HPA7","HPA8","HPA9","HPA10","HPA11","HPA12","HPA13","HPA14","HPA15","HPA16","HPA17",
            "frame4", "HPB5","HPB6","HPB7","HPB8","HPB9","HPB10","HPB11","HPB12","HPB13","HPB14","HPB15","HPB16","HPB17",
            "frame5", "HPC5","HPC6","HPC7","HPC8","HPC9","HPC10","HPC11","HPC12","HPC13","HPC14","HPC15","HPC16","HPC17",
            "frame6", "HPD5","HPD6","HPD7","HPD8","HPD9","HPD10","HPD11","HPD12","HPD13","HPD14","HPD15","HPD16","HPD17"
        ]

        # Construct the SQL
        placeholders = ", ".join(["?" for _ in range(len(columns))])
        query = f"INSERT INTO scomms_logs ({', '.join(columns)}) VALUES ({placeholders})"
        
        cursor.execute(query, [ts_string] + combined_payload)
        
        _frame_count += 1
        if _frame_count % 5 == 0:
            _conn.commit()
            
    except Exception as e:
        print(f"❌ Database Insertion Error: {e}")
