# Funciones auxiliares
from datetime import datetime
from dateutil.relativedelta import relativedelta  

def calculate_next_reminder(last_analysis: dict | None) -> datetime | None:
    if not last_analysis:
        return None
    return last_analysis["date"] + relativedelta(months=3)