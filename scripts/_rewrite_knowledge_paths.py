import sqlite3
from pathlib import Path
db = Path(r"C:\gokuai\DataIndex\minecraft-knowledge\knowledge.v5.1787973154.db")
con = sqlite3.connect(str(db))
old = "C:\\rmblocal_llm\\knowledge"
new = "C:\\gokuai\\Data"
n_old = con.execute("SELECT COUNT(*) FROM files WHERE physical_path LIKE ?", (old + "%",)).fetchone()[0]
print("before_old", n_old)
cur = con.execute(
    "UPDATE files SET physical_path = REPLACE(physical_path, ?, ?), source_root = REPLACE(IFNULL(source_root,''), ?, ?) WHERE physical_path LIKE ? OR IFNULL(source_root,'') LIKE ?",
    (old, new, old, new, old + "%", old + "%"),
)
con.commit()
print("rowcount", cur.rowcount)
n_old2 = con.execute("SELECT COUNT(*) FROM files WHERE physical_path LIKE ?", (old + "%",)).fetchone()[0]
n_new = con.execute("SELECT COUNT(*) FROM files WHERE physical_path LIKE ?", (new + "%",)).fetchone()[0]
print("after_old", n_old2, "after_new", n_new)
for r in con.execute("SELECT physical_path, source_root FROM files WHERE source_id='local' LIMIT 5"):
    print(r)
con.close()
