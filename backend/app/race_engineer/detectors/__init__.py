"""Race Engineer detectors: one module per family of callouts."""

from app.race_engineer.detectors.base import Detector, Sustained
from app.race_engineer.detectors.coaching import CoachingDetector
from app.race_engineer.detectors.engine import EngineDetector
from app.race_engineer.detectors.fuel import FuelDetector
from app.race_engineer.detectors.lap import LapDetector
from app.race_engineer.detectors.pace import PaceDetector
from app.race_engineer.detectors.race import RaceDetector
from app.race_engineer.detectors.tires import TireDetector

__all__ = [
    "CoachingDetector",
    "Detector",
    "EngineDetector",
    "FuelDetector",
    "LapDetector",
    "PaceDetector",
    "RaceDetector",
    "Sustained",
    "TireDetector",
]
