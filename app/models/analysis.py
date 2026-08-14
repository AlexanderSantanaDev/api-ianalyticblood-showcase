# Modelos de análisis
from typing import Literal, Tuple, List, Optional
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
  
# Modelos para las secciones de análisis detallado con viñetas.
class AnalysisSectionItem(BaseModel):
    text: str
    is_real: bool = True  # En análisis de usuario registrado siempre son reales

class AnalysisSection(BaseModel):
    title: str
    subtitle: str
    icon: str
    items: List[AnalysisSectionItem]
    hidden_count: int = 0  # Para usuarios registrados no hay items ocultos en BD

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
    # analysis_sections opcional — presente en plan premium,
    # ausente o vacío en plan free. El frontend controla el tease según el plan del usuario.
    analysis_sections: Optional[List[AnalysisSection]] = Field(default_factory=list)
  
class AnalysisCreate(AnalysisBase):
  pass

class Analysis(AnalysisBase):
  id: str
  date: datetime