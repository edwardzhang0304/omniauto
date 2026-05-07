@echo off
set WECHAT_KNOWLEDGE_TENANT=jiangsu_chejin_usedcar_customer_20260501
set PYTHONPATH=D:\AI\omniauto
"D:\AI\omniauto\.venv\Scripts\python.exe" -m apps.wechat_ai_customer_service.workflows.listen_and_reply --send
