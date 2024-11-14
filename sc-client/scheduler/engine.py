from datetime import datetime, timedelta
from typing import List, Optional
from .models import Meeting, TimeRange, Participant
from .costs import SchedulingCosts

class SchedulingConstraint:
    def can_schedule(self, meeting: Meeting, time_range: TimeRange) -> bool:
        raise NotImplementedError

class WorkingHoursConstraint(SchedulingConstraint):
    def can_schedule(self, meeting: Meeting, time_range: TimeRange) -> bool:
        return all(p.is_available(time_range) for p in meeting.required_participants)

class TimezoneSafetyConstraint(SchedulingConstraint):
    def __init__(self, earliest_hour: int = 6, latest_hour: int = 22):
        self.earliest_hour = earliest_hour
        self.latest_hour = latest_hour

    def can_schedule(self, meeting: Meeting, time_range: TimeRange) -> bool:
        for participant in meeting.required_participants:
            local_start = time_range.start.astimezone(participant.timezone)
            local_end = time_range.end.astimezone(participant.timezone)
            
            if (local_start.hour < self.earliest_hour or 
                local_end.hour > self.latest_hour):
                return False
        return True

class SchedulingStrategy:
    def prioritize(self, meetings: List[Meeting]) -> List[Meeting]:
        raise NotImplementedError

class TotalUserTimeStrategy(SchedulingStrategy):
    def prioritize(self, meetings: List[Meeting]) -> List[Meeting]:
        return sorted(meetings, 
                     key=lambda m: m.total_user_time,
                     reverse=True)

class MeetingScheduler:
    def __init__(self,
                 strategy: SchedulingStrategy,
                 constraints: List[SchedulingConstraint],
                 costs: SchedulingCosts,
                 time_slot_increment: timedelta = timedelta(minutes=15)):
        self.strategy = strategy
        self.constraints = constraints
        self.costs = costs
        self.time_slot_increment = time_slot_increment
        self.debug = True

    def schedule(self, meetings: List[Meeting]) -> List[Meeting]:
        """
        Schedule a list of meetings according to the configured strategy and constraints.
        Returns the list of meetings with their scheduled times (some may remain unscheduled).
        """
        # First, prioritize meetings according to strategy
        prioritized_meetings = self.strategy.prioritize(meetings)
        
        if self.debug:
            print("\nScheduling meetings in priority order:")
            for meeting in prioritized_meetings:
                print(f"- {meeting.title} ({len(meeting.participants)} participants)")
        
        # Try to schedule each meeting
        for meeting in prioritized_meetings:
            if self.debug:
                print(f"\nAttempting to schedule: {meeting.title}")
                print(f"Duration: {meeting.duration}")
                print("Required participants:", 
                      [p.user_id for p in meeting.required_participants])
            
            best_slot = self._find_best_slot(meeting)
            
            if best_slot:
                if self.debug:
                    print(f"Found slot: {best_slot.start} - {best_slot.end} (UTC)")
                
                # Assign the time slot to the meeting
                meeting.scheduled_time = best_slot
                
                # Update participant schedules
                for participant in meeting.participants:
                    participant.schedule_meeting(best_slot)
            else:
                if self.debug:
                    print(f"Failed to find valid slot for: {meeting.title}")
        
        return prioritized_meetings

    def _find_best_slot(self, meeting: Meeting) -> Optional[TimeRange]:
        current_time = meeting.earliest_start
        end_time = meeting.latest_end or (current_time + timedelta(days=30))
        
        best_slot = None
        best_cost = float('inf')
        
        if self.debug:
            print(f"\nSearching for slots between {current_time} and {end_time}")
        
        slots_checked = 0
        valid_slots_found = 0
        
        while current_time + meeting.duration <= end_time:
            time_range = TimeRange(current_time, current_time + meeting.duration)
            slots_checked += 1
            
            # Check constraints
            if self._is_valid_slot(meeting, time_range):
                valid_slots_found += 1
                cost = self.costs.calculate_total_cost(time_range, meeting.participants)
                
                if self.debug and valid_slots_found % 50 == 0:
                    print(f"Found {valid_slots_found} valid slots so far...")
                
                if cost < best_cost:  # Remove max_cost check
                    best_slot = time_range
                    best_cost = cost
                    
                    if self.debug:
                        print(f"New best slot found: {current_time} (UTC) - Cost: {cost:.2f}")
                    
                    # If we found a very good slot (negative cost), use it immediately
                    if cost < 0:
                        break
            
            current_time += self.time_slot_increment
        
        if self.debug:
            print(f"Checked {slots_checked} slots total")
            print(f"Found {valid_slots_found} valid slots")
            if best_slot:
                print(f"Best slot cost: {best_cost:.2f}")
        
        return best_slot  # Will now always return the best slot found, even with high cost

    def _is_valid_slot(self, meeting: Meeting, time_range: TimeRange) -> bool:
        if self.debug:
            for constraint in self.constraints:
                if not constraint.can_schedule(meeting, time_range):
                    constraint_name = constraint.__class__.__name__
                    return False
            return True
        return all(constraint.can_schedule(meeting, time_range) 
                  for constraint in self.constraints)

class SchedulerBuilder:
    def __init__(self):
        self.strategy = TotalUserTimeStrategy()
        self.constraints = [
            WorkingHoursConstraint(),
            TimezoneSafetyConstraint()
        ]
        self.time_slot_increment = timedelta(minutes=15)
        self.costs = SchedulingCosts()

    def with_strategy(self, strategy: SchedulingStrategy) -> 'SchedulerBuilder':
        self.strategy = strategy
        return self

    def with_constraint(self, constraint: SchedulingConstraint) -> 'SchedulerBuilder':
        self.constraints.append(constraint)
        return self

    def with_time_increment(self, increment: timedelta) -> 'SchedulerBuilder':
        self.time_slot_increment = increment
        return self
        
    def with_costs(self, costs: SchedulingCosts) -> 'SchedulerBuilder':
        self.costs = costs
        return self

    def build(self) -> MeetingScheduler:
        return MeetingScheduler(
            strategy=self.strategy,
            constraints=self.constraints,
            costs=self.costs,
            time_slot_increment=self.time_slot_increment
        )