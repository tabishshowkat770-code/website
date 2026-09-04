import streamlit as st
import sqlite3
from datetime import datetime, date
import os
import io
import csv
import hashlib
import binascii
from io import BytesIO
import streamlit as st

# optional: use pandas/openpyxl for Excel export if available
try:
	import pandas as pd
	PANDAS_AVAILABLE = True
except Exception:
	PANDAS_AVAILABLE = False


DB_PATH = os.path.join(os.getcwd(), "tasks.db")


@st.cache_resource
def get_conn(path=DB_PATH):
	conn = sqlite3.connect(path, check_same_thread=False)
	conn.row_factory = sqlite3.Row
	init_db(conn)
	return conn


def init_db(conn):
	conn.execute(
		"""
		CREATE TABLE IF NOT EXISTS tasks (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			title TEXT NOT NULL,
			description TEXT,
			due_date TEXT,
			priority TEXT,
			status TEXT,
			created_at TEXT,
			updated_at TEXT
		)
		"""
	)
	conn.commit()

	# create users table
	conn.execute(
		"""
		CREATE TABLE IF NOT EXISTS users (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			username TEXT NOT NULL UNIQUE,
			password_hash TEXT NOT NULL,
			salt TEXT NOT NULL,
			created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
		)
		"""
	)

	# ensure tasks has user_id
	cur = conn.execute("PRAGMA table_info(tasks)")
	cols = [r[1] for r in cur.fetchall()]
	if "user_id" not in cols:
		conn.execute("ALTER TABLE tasks ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")

	conn.commit()


def add_task(conn, title, description, due_date, priority, status):
	now = datetime.utcnow().isoformat()
	user_id = st.session_state.get("user_id", 1)
	conn.execute(
		"INSERT INTO tasks (title, description, due_date, priority, status, created_at, updated_at, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
		(title, description, due_date, priority, status, now, now, user_id),
	)
	conn.commit()


def update_task(conn, task_id, title, description, due_date, priority, status):
	now = datetime.utcnow().isoformat()
	user_id = st.session_state.get("user_id", 1)
	conn.execute(
		"UPDATE tasks SET title=?, description=?, due_date=?, priority=?, status=?, updated_at=? WHERE id=? AND user_id=?",
		(title, description, due_date, priority, status, now, task_id, user_id),
	)
	conn.commit()


def delete_task(conn, task_id):
	user_id = st.session_state.get("user_id", 1)
	conn.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
	conn.commit()



def get_tasks(conn, status=None, priority=None, search=None, sort_by="due_date"):
	user_id = st.session_state.get("user_id", 1)
	query = "SELECT * FROM tasks WHERE user_id=?"
	filters = []
	params = [user_id]
	if status and status != "All":
		filters.append("status = ?")
		params.append(status)
	if priority and priority != "All":
		filters.append("priority = ?")
		params.append(priority)
	if search:
		filters.append("(title LIKE ? OR description LIKE ?)")
		params.extend([f"%{search}%", f"%{search}%"])
	if filters:
		query += " AND " + " AND ".join(filters)
	if sort_by:
		query += f" ORDER BY {sort_by}"
	cur = conn.execute(query, params)
	return [dict(row) for row in cur.fetchall()]


def tasks_to_dataframe(tasks):
	if PANDAS_AVAILABLE:
		return pd.DataFrame(tasks)
	# fallback simple conversion
	if not tasks:
		return []
	keys = tasks[0].keys()
	rows = [[t[k] for k in keys] for t in tasks]
	return (keys, rows)


def export_csv(tasks):
	keys = tasks[0].keys() if tasks else []
	output = io.StringIO()
	writer = csv.DictWriter(output, fieldnames=keys)
	writer.writeheader()
	for t in tasks:
		writer.writerow(t)
	return output.getvalue().encode("utf-8")


def export_excel(tasks):
	# requires pandas and an Excel engine (openpyxl or xlsxwriter)
	if not PANDAS_AVAILABLE:
		return None
	df = pd.DataFrame(tasks)
	bio = io.BytesIO()
	engine = None
	try:
		import openpyxl  # noqa: F401
		engine = "openpyxl"
	except Exception:
		try:
			import xlsxwriter  # noqa: F401
			engine = "xlsxwriter"
		except Exception:
			return None
	with pd.ExcelWriter(bio, engine=engine) as writer:
		df.to_excel(writer, index=False, sheet_name="tasks")
	bio.seek(0)
	return bio.read()


def main():
	st.set_page_config(page_title="Task Manager", layout="wide")
	conn = get_conn()

	# initialize auth state
	if "user_id" not in st.session_state:
		st.session_state.user_id = None
	if "username" not in st.session_state:
		st.session_state.username = None

	# auth helpers
	def hash_password(password: str, salt: bytes = None):
		if salt is None:
			salt = os.urandom(16)
		pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
		return binascii.hexlify(pwd_hash).decode(), binascii.hexlify(salt).decode()

	def verify_password(stored_hash_hex: str, stored_salt_hex: str, provided_password: str) -> bool:
		salt = binascii.unhexlify(stored_salt_hex)
		pwd_hash = hashlib.pbkdf2_hmac("sha256", provided_password.encode("utf-8"), salt, 100_000)
		return binascii.hexlify(pwd_hash).decode() == stored_hash_hex

	def create_user(username: str, password: str):
		h, s = hash_password(password)
		c = get_conn()
		try:
			c.execute("INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)", (username, h, s))
			c.commit()
			return True
		except sqlite3.IntegrityError:
			return False

	def authenticate_user(username: str, password: str):
		c = get_conn()
		cur = c.execute("SELECT id, password_hash, salt FROM users WHERE username=?", (username,))
		row = cur.fetchone()
		if not row:
			return None
		user_id, stored_hash, stored_salt = row
		if verify_password(stored_hash, stored_salt, password):
			return user_id
		return None

	# Authentication UI in sidebar
	with st.sidebar:
		st.title("Account")
		if st.session_state.user_id:
			st.markdown(f"**Signed in as:** {st.session_state.get('username')}")
			if st.button("Log out"):
				st.session_state.user_id = None
				st.session_state.username = None
				st.rerun()
			# export button
			if st.button("Download tasks (.csv)"):
				tasks = get_tasks(conn)
				csv_data = export_csv(tasks)
				st.download_button("Download CSV", csv_data, file_name="tasks.csv", mime="text/csv")
		else:
			tab = st.tabs(["Login", "Register"])
			with tab[0]:
				lu = st.text_input("Username", key="login_user")
				lp = st.text_input("Password", type="password", key="login_pass")
				if st.button("Login"):
					uid = authenticate_user(lu.strip(), lp)
					if uid:
						st.session_state.user_id = uid
						st.session_state.username = lu.strip()
						st.rerun()
					else:
						st.error("Invalid username or password")
			with tab[1]:
				ru = st.text_input("Choose a username", key="reg_user")
				rp = st.text_input("Choose a password", type="password", key="reg_pass")
				if st.button("Register"):
					if not ru.strip() or not rp:
						st.error("Please provide username and password")
					else:
						ok = create_user(ru.strip(), rp)
						if ok:
							st.success("Account created — you can log in now")
						else:
							st.error("Username already exists")

	# require login
	if not st.session_state.user_id:
		st.warning("Please log in or register to view and manage your tasks.")
		st.stop()

	st.title("Simple Task Manager (single-file)")

	# Top instructions
	with st.expander("About / Deploy instructions", expanded=False):
		st.markdown(
			"""
			- Single-file Streamlit app using SQLite for persistence.
			- To deploy on Streamlit Cloud: create a GitHub repo and push this `web.py` to the root. Optionally add `requirements.txt`.
			- Minimal `requirements.txt`:
			  ```
			  streamlit
			  pandas # optional, for Excel export
			  openpyxl # optional, for Excel export
			  ```
			- On Streamlit Cloud choose the repo and the file `web.py` as the app entrypoint.
			"""
		)

	# Sidebar: filters and add form toggle
	st.sidebar.header("Filters & Add")
	status_filter = st.sidebar.selectbox("Status", ["All", "Todo", "In Progress", "Done"], index=0)
	priority_filter = st.sidebar.selectbox("Priority", ["All", "Low", "Medium", "High"], index=0)
	search = st.sidebar.text_input("Search title or description")
	sort_by = st.sidebar.selectbox("Sort by", ["due_date", "created_at", "priority"], index=0)

	with st.sidebar.expander("Add new task"):
		new_title = st.text_input("Title", key="new_title")
		new_desc = st.text_area("Description", key="new_desc")
		new_due = st.date_input("Due date", value=date.today(), key="new_due")
		new_priority = st.selectbox("Priority", ["Low", "Medium", "High"], index=1, key="new_priority")
		new_status = st.selectbox("Status", ["Todo", "In Progress", "Done"], index=0, key="new_status")
		if st.button("Add Task"):
			if not new_title.strip():
				st.warning("Please enter a title")
			else:
				add_task(conn, new_title.strip(), new_desc.strip(), new_due.isoformat(), new_priority, new_status)
				st.rerun()

	# Load tasks
	tasks = get_tasks(conn, status=status_filter, priority=priority_filter, search=search, sort_by=sort_by)

	st.subheader(f"Tasks — {len(tasks)}")

	# Export controls
	if tasks:
		if PANDAS_AVAILABLE:
			if st.button("Download Excel (.xlsx)"):
				data = export_excel(tasks)
				if data is None:
					st.error("Excel export requires openpyxl or xlsxwriter. Install with: pip install openpyxl or pip install xlsxwriter")
				else:
					st.download_button("Click to download .xlsx", data, file_name="tasks.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
		csv_data = export_csv(tasks)
		st.download_button("Download CSV", csv_data, file_name="tasks.csv", mime="text/csv")

	# Show tasks with action buttons
	for t in tasks:
		cols = st.columns([3, 6, 2, 1])
		with cols[0]:
			st.markdown(f"**{t['title']}**")
			if t.get("description"):
				st.caption(t.get("description"))
		with cols[1]:
			st.write(f"Due: {t.get('due_date') or '-'} — Priority: {t.get('priority') or '-'}")
			st.write(f"Status: {t.get('status') or '-'}")
		with cols[2]:
			if st.button("Edit", key=f"edit_{t['id']}"):
				st.session_state.editing = t['id']
		with cols[3]:
			if st.button("Delete", key=f"del_{t['id']}"):
				delete_task(conn, t['id'])
				st.rerun()

		# If editing this task, show form
		if st.session_state.get("editing") == t['id']:
			with st.form(key=f"form_{t['id']}"):
				e_title = st.text_input("Title", value=t['title'])
				e_desc = st.text_area("Description", value=t['description'])
				e_due = st.date_input("Due date", value=datetime.fromisoformat(t['due_date']).date() if t.get('due_date') else date.today())
				e_priority = st.selectbox("Priority", ["Low", "Medium", "High"], index=["Low", "Medium", "High"].index(t.get('priority') or "Medium"))
				e_status = st.selectbox("Status", ["Todo", "In Progress", "Done"], index=["Todo", "In Progress", "Done"].index(t.get('status') or "Todo"))
				if st.form_submit_button("Save"):
					update_task(conn, t['id'], e_title.strip(), e_desc.strip(), e_due.isoformat(), e_priority, e_status)
					st.session_state.editing = None
					st.rerun()
				if st.form_submit_button("Cancel"):
					st.session_state.editing = None
					st.rerun()


if __name__ == "__main__":
	main()

