import streamlit as st
import sqlite3
from datetime import datetime, date
import os
import io
import csv

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


def add_task(conn, title, description, due_date, priority, status):
	now = datetime.utcnow().isoformat()
	conn.execute(
		"INSERT INTO tasks (title, description, due_date, priority, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
		(title, description, due_date, priority, status, now, now),
	)
	conn.commit()


def update_task(conn, task_id, title, description, due_date, priority, status):
	now = datetime.utcnow().isoformat()
	conn.execute(
		"UPDATE tasks SET title=?, description=?, due_date=?, priority=?, status=?, updated_at=? WHERE id=?",
		(title, description, due_date, priority, status, now, task_id),
	)
	conn.commit()


def delete_task(conn, task_id):
	conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
	conn.commit()


def get_tasks(conn, status=None, priority=None, search=None, sort_by="due_date"):
	query = "SELECT * FROM tasks"
	filters = []
	params = []
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
		query += " WHERE " + " AND ".join(filters)
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
	# requires pandas + openpyxl
	df = pd.DataFrame(tasks)
	bio = io.BytesIO()
	with pd.ExcelWriter(bio, engine="openpyxl") as writer:
		df.to_excel(writer, index=False, sheet_name="tasks")
	bio.seek(0)
	return bio.read()


def main():
	st.set_page_config(page_title="Task Manager", layout="wide")
	conn = get_conn()

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
				st.experimental_rerun()

	# Load tasks
	tasks = get_tasks(conn, status=status_filter, priority=priority_filter, search=search, sort_by=sort_by)

	st.subheader(f"Tasks — {len(tasks)}")

	# Export controls
	if tasks:
		if PANDAS_AVAILABLE:
			if st.button("Download Excel (.xlsx)"):
				data = export_excel(tasks)
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
				st.experimental_rerun()

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
					st.experimental_rerun()
				if st.form_submit_button("Cancel"):
					st.session_state.editing = None
					st.experimental_rerun()


if __name__ == "__main__":
	main()

