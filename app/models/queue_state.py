"""Queue state model matching real FreePBX/Asterisk queue status format."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class QueueInfo:
    """Individual queue information — matches FreePBX queuestatus.php format."""
    Event: str = "QueueParams"
    Queue: str = ""
    Max: int = 0
    Strategy: str = "ringall"
    Calls: int = 0
    Holdtime: int = 0
    TalkTime: int = 0
    Completed: int = 0
    Abandoned: int = 0
    ServiceLevel: int = 135
    ServicelevelPerf: float = 0.0
    ServicelevelPerf2: float = 0.0
    Weight: int = 0
    AvailableAgents: int = 0


@dataclass
class GlobalQueueState:
    """Aggregated queue state across all queues."""
    global_calls_waiting: int = 0
    global_max_holdtime: int = 0
    global_agents_available: int = 0
    outbound_allowed: bool = False
    stable_polls_count: int = 0
    last_poll_time: Optional[datetime] = None
    ami_connected: bool = True
    queues: list[QueueInfo] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "global_calls_waiting": self.global_calls_waiting,
            "global_max_holdtime": self.global_max_holdtime,
            "global_agents_available": self.global_agents_available,
            "outbound_allowed": self.outbound_allowed,
            "stable_polls_count": self.stable_polls_count,
            "last_poll_time": self.last_poll_time.isoformat() if self.last_poll_time else None,
            "ami_connected": self.ami_connected,
            "queues": [
                {
                    "Event": q.Event,
                    "Queue": q.Queue,
                    "Max": q.Max,
                    "Strategy": q.Strategy,
                    "Calls": q.Calls,
                    "Holdtime": q.Holdtime,
                    "TalkTime": q.TalkTime,
                    "Completed": q.Completed,
                    "Abandoned": q.Abandoned,
                    "ServiceLevel": q.ServiceLevel,
                    "ServicelevelPerf": q.ServicelevelPerf,
                    "ServicelevelPerf2": q.ServicelevelPerf2,
                    "Weight": q.Weight,
                    "AvailableAgents": q.AvailableAgents,
                }
                for q in self.queues
            ],
        }
