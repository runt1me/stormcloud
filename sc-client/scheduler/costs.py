from datetime import datetime, time, timedelta
from typing import List, Optional
import math
import pytz
from .models import TimeRange, WorkingHours, Participant, ParticipantRole

class SchedulingCosts:
    def __init__(self,
                 outside_hours_base_cost: float = 5.0,
                 outside_hours_exp_factor: float = 1.5,
                 early_meeting_penalty: float = 2.0,
                 late_meeting_penalty: float = 2.0,
                 preferred_hour_bonus: float = -2.0,
                 consecutive_meeting_penalty: float = 1.0,
                 timezone_span_penalty: float = 0.5,
                 required_double_booking_penalty: float = 50.0,
                 optional_double_booking_penalty: float = 20.0):
        self.outside_hours_base_cost = outside_hours_base_cost
        self.outside_hours_exp_factor = outside_hours_exp_factor
        self.early_meeting_penalty = early_meeting_penalty
        self.late_meeting_penalty = late_meeting_penalty
        self.preferred_hour_bonus = preferred_hour_bonus
        self.consecutive_meeting_penalty = consecutive_meeting_penalty
        self.timezone_span_penalty = timezone_span_penalty
        self.required_double_booking_penalty = required_double_booking_penalty
        self.optional_double_booking_penalty = optional_double_booking_penalty

    def calculate_time_distance(self, dt: datetime, working_hours: WorkingHours) -> timedelta:
        """Calculate minimum distance to any working hours block"""
        if dt.tzinfo is None:
            dt = pytz.UTC.localize(dt)
            
        time_of_day = dt.time()
        min_distance = timedelta.max

        for start, end in working_hours.ranges:
            if start <= time_of_day <= end:
                return timedelta()
            
            start_dt = pytz.UTC.localize(
                datetime.combine(dt.date(), start)
            )
            end_dt = pytz.UTC.localize(
                datetime.combine(dt.date(), end)
            )
            
            if time_of_day < start:
                dist = start_dt - dt
                min_distance = min(min_distance, abs(dist))
                
            if time_of_day > end:
                dist = dt - end_dt
                min_distance = min(min_distance, abs(dist))

        return min_distance

    def outside_hours_cost(self, time_range: TimeRange, participant: Participant) -> float:
        """Calculate cost for scheduling outside working hours"""
        local_start = time_range.start.astimezone(participant.timezone)
        local_end = time_range.end.astimezone(participant.timezone)
        
        start_distance = self.calculate_time_distance(local_start, participant.working_hours)
        end_distance = self.calculate_time_distance(local_end, participant.working_hours)
        
        max_distance_minutes = max(start_distance, end_distance).total_seconds() / 60
        
        if max_distance_minutes == 0:
            return 0
        
        return self.outside_hours_base_cost * math.pow(
            max_distance_minutes, self.outside_hours_exp_factor
        )

    def time_of_day_cost(self, dt: datetime, participant: Participant) -> float:
        """Calculate cost based on time of day preferences"""
        local_time = dt.astimezone(participant.timezone)
        hour = local_time.hour
        
        if hour < 9:
            return self.early_meeting_penalty * (9 - hour)
        
        if hour >= 16:
            return self.late_meeting_penalty * (hour - 15)
            
        if 10 <= hour < 15:
            return self.preferred_hour_bonus
            
        return 0

    def consecutive_meeting_cost(self, time_range: TimeRange, 
                               participant: Participant,
                               buffer_minutes: int = 15) -> float:
        """Calculate cost for meetings too close together"""
        buffer = timedelta(minutes=buffer_minutes)
        
        for existing_meeting in participant.scheduled_meetings:
            if abs(time_range.start - existing_meeting.end) < buffer or \
               abs(time_range.end - existing_meeting.start) < buffer:
                return self.consecutive_meeting_penalty
                
        return 0

    def double_booking_cost(self, time_range: TimeRange, participant: Participant) -> float:
        """Calculate cost for double-booking a participant"""
        overlapping = participant.get_overlapping_meetings(time_range)
        if not overlapping:
            return 0.0
            
        if participant.role in (ParticipantRole.REQUIRED, ParticipantRole.ORGANIZER):
            return self.required_double_booking_penalty * len(overlapping)
        else:
            return self.optional_double_booking_penalty * len(overlapping)

    def timezone_span_cost(self, participants: List[Participant], 
                          time_range: TimeRange) -> float:
        """Calculate cost based on timezone spread"""
        local_times = []
        for participant in participants:
            local_time = time_range.start.astimezone(participant.timezone)
            local_times.append(local_time.hour)
        
        hour_span = max(local_times) - min(local_times)
        return self.timezone_span_penalty * hour_span

    def calculate_total_cost(self, time_range: TimeRange, 
                           participants: List[Participant]) -> float:
        """Calculate total scheduling cost"""
        total_cost = 0
        
        for participant in participants:
            total_cost += self.outside_hours_cost(time_range, participant)
            total_cost += self.time_of_day_cost(time_range.start, participant)
            total_cost += self.consecutive_meeting_cost(time_range, participant)
            total_cost += self.double_booking_cost(time_range, participant)
        
        total_cost += self.timezone_span_cost(participants, time_range)
        
        return total_cost