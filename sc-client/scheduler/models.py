from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import List, Optional, Set, Tuple
from enum import Enum
import pytz

class ParticipantRole(Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    ORGANIZER = "organizer"

@dataclass(frozen=True)  # Make TimeRange immutable and hashable
class TimeRange:
    start: datetime
    end: datetime

    def __post_init__(self):
        # Since the dataclass is frozen, we need to use object.__setattr__ to modify fields
        if self.start.tzinfo is None:
            object.__setattr__(self, 'start', pytz.UTC.localize(self.start))
        if self.end.tzinfo is None:
            object.__setattr__(self, 'end', pytz.UTC.localize(self.end))

    def overlaps(self, other: 'TimeRange') -> bool:
        return (self.start < other.end and self.end > other.start)

    def contains(self, dt: datetime) -> bool:
        if dt.tzinfo is None:
            dt = pytz.UTC.localize(dt)
        return self.start <= dt <= self.end

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

class WorkingHours:
    def __init__(self, ranges: List[Tuple[time, time]]):
        # Sort and validate ranges don't overlap
        self.ranges = sorted(ranges, key=lambda x: x[0])
        self._validate_ranges()

    def _validate_ranges(self):
        """Ensure time ranges don't overlap and are valid"""
        for i in range(len(self.ranges) - 1):
            curr_end = self.ranges[i][1]
            next_start = self.ranges[i + 1][0]
            if curr_end >= next_start:
                raise ValueError(
                    f"Working hour ranges overlap or touch: "
                    f"{curr_end.strftime('%H:%M')} and {next_start.strftime('%H:%M')}"
                )

    @classmethod
    def from_string(cls, time_str: str) -> 'WorkingHours':
        """
        Parse working hours from string format.
        Supports multiple formats:
        - Simple range: "9:00-17:00"
        - Multiple ranges: "9:00-12:00,13:00-17:00"
        - Tuple syntax: "((9:00,12:00),(13:00,17:00))"
        """
        # Remove all whitespace
        time_str = "".join(time_str.split())
        
        # Check if using tuple syntax
        if time_str.startswith("((") and time_str.endswith("))"):
            # Remove outer parentheses and split on "),(""
            ranges_str = time_str[2:-2].split("),(")
        else:
            # Treat as comma-separated ranges
            ranges_str = time_str.split(",")
        
        ranges = []
        for range_str in ranges_str:
            if "-" in range_str:
                start_str, end_str = range_str.split("-")
            else:
                start_str, end_str = range_str.split(",")
                
            try:
                start = datetime.strptime(start_str.strip(), '%H:%M').time()
                end = datetime.strptime(end_str.strip(), '%H:%M').time()
                ranges.append((start, end))
            except ValueError as e:
                raise ValueError(
                    f"Invalid time format. Use HH:MM. Error in '{range_str}': {e}"
                )
        
        return cls(ranges)

    @classmethod
    def with_lunch_break(cls, 
                        work_start: str,
                        lunch_start: str,
                        lunch_end: str,
                        work_end: str) -> 'WorkingHours':
        """
        Convenience method to create working hours with a lunch break.
        
        Example:
        >>> hours = WorkingHours.with_lunch_break("9:00", "12:00", "13:00", "17:00")
        """
        return cls.from_string(f"{work_start}-{lunch_start},{lunch_end}-{work_end}")

    def get_available_ranges(self, date: datetime) -> List[TimeRange]:
        """Convert working hours to actual datetime ranges for a specific date"""
        if date.tzinfo is None:
            date = pytz.UTC.localize(date)
            
        ranges = []
        base_date = date.date()
        for start_time, end_time in self.ranges:
            start = pytz.UTC.localize(datetime.combine(base_date, start_time))
            end = pytz.UTC.localize(datetime.combine(base_date, end_time))
            ranges.append(TimeRange(start, end))
        return ranges

    def __str__(self) -> str:
        """String representation of working hours"""
        ranges_str = []
        for start, end in self.ranges:
            ranges_str.append(f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}")
        return ",".join(ranges_str)

class Participant:
    def __init__(self, 
                 user_id: str,
                 role: ParticipantRole,
                 timezone: str,
                 working_hours: WorkingHours):
        self.user_id = user_id
        self.role = role
        self.timezone = pytz.timezone(timezone)
        self.working_hours = working_hours
        self.scheduled_meetings: List[TimeRange] = []

    def is_available(self, time_range: TimeRange) -> bool:
        # Convert proposed time to participant's timezone
        local_range = TimeRange(
            time_range.start.astimezone(self.timezone),
            time_range.end.astimezone(self.timezone)
        )
        
        # Check if time is within working hours
        date_ranges = self.working_hours.get_available_ranges(local_range.start)
        if not any(r.contains(local_range.start) and r.contains(local_range.end) 
                  for r in date_ranges):
            return False

        return True

    def schedule_meeting(self, time_range: TimeRange):
        """Add a meeting to this participant's schedule"""
        self.scheduled_meetings.append(time_range)

    def get_overlapping_meetings(self, time_range: TimeRange) -> List[TimeRange]:
        """Return list of meetings that overlap with the given time range"""
        return [meeting for meeting in self.scheduled_meetings 
                if meeting.overlaps(time_range)]

    def clear_schedule(self):
        """Clear all scheduled meetings"""
        self.scheduled_meetings = []

class Meeting:
    def __init__(self,
                 title: str,
                 duration: timedelta,
                 participants: List[Participant],
                 earliest_start: Optional[datetime] = None,
                 latest_end: Optional[datetime] = None):
        self.title = title
        self.duration = duration
        self.participants = participants
        
        # Ensure timezone-aware datetimes
        if earliest_start is None:
            earliest_start = datetime.now()
        if earliest_start.tzinfo is None:
            earliest_start = pytz.UTC.localize(earliest_start)
        self.earliest_start = earliest_start

        if latest_end is not None and latest_end.tzinfo is None:
            latest_end = pytz.UTC.localize(latest_end)
        self.latest_end = latest_end
        
        self.scheduled_time: Optional[TimeRange] = None

    @property
    def is_scheduled(self) -> bool:
        return self.scheduled_time is not None

    @property
    def total_user_time(self) -> timedelta:
        return self.duration * len(self.participants)

    @property
    def required_participants(self) -> List[Participant]:
        return [p for p in self.participants 
                if p.role in (ParticipantRole.REQUIRED, ParticipantRole.ORGANIZER)]