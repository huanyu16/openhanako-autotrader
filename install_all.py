import os, json
D = os.path.expanduser("~/Desktop/oulay-trader")
for s in ["shared","servers","config","data","logs"]: os.makedirs(f"{D}/{s}", exist_ok=True)

# 标记文件已就绪
open(f"{D}/shared/__init__.py","w").write("# Oula Trading\n")
print("READY")
