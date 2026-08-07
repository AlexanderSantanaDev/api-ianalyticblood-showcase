# Modelos de análisis
from typing import Literal, Tuple
from pydantic import BaseModel, Field
from datetime import datetime

class Parameter(BaseModel):
    value: float | None
    unit: str | None
    status: Literal["normal", "bajo", "alto", "muy_alto"] | None
    reference_range: Tuple[float | None, float | None] | None = None

class Overview(BaseModel):
    alert_level: Literal["normal", "attention", "alert"]
    general_state: str
    summary: str
  
class AnalysisBase(BaseModel):
    user_id: str
    file_type: str
    overview: Overview
    parameters: dict[str, Parameter]
    analysis: list[str]
    # recommendations ahora es opcional con default [].
    # DeepSeek a veces omite este campo (especialmente en plan free)
    # provocando un ValidationError. Con Field(default_factory=list)
    # Pydantic usa [] si el campo no viene en la respuesta de la IA.
    recommendations: list[str] = Field(default_factory=list)
  
class AnalysisCreate(AnalysisBase):
  pass

class Analysis(AnalysisBase):
  id: str
  date: datetime