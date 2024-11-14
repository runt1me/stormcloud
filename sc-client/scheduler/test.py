from datetime import datetime, timedelta
import pytz
from .models import (Meeting, Participant, ParticipantRole, 
                    WorkingHours, TimeRange)  # Add TimeRange import
from .engine import SchedulerBuilder
from .costs import SchedulingCosts

def create_test_participants():
    """Create a diverse set of participants with various time zones"""
    participants = [
        # New York team (4 people)
        Participant(
            user_id="ny_lead",
            role=ParticipantRole.ORGANIZER,
            timezone="America/New_York",
            working_hours=WorkingHours.with_lunch_break("9:00", "12:00", "13:00", "17:00")
        ),
        Participant(
            user_id="ny_dev1",
            role=ParticipantRole.REQUIRED,
            timezone="America/New_York",
            working_hours=WorkingHours.from_string("8:00-16:00")  # Early schedule
        ),
        Participant(
            user_id="ny_dev2",
            role=ParticipantRole.REQUIRED,
            timezone="America/New_York",
            working_hours=WorkingHours.from_string("10:00-18:00")  # Late schedule
        ),
        Participant(
            user_id="ny_flex",
            role=ParticipantRole.OPTIONAL,
            timezone="America/New_York",
            working_hours=WorkingHours.from_string("7:00-19:00")  # Flexible hours
        ),
        
        # West Coast team (2 people)
        Participant(
            user_id="sf_lead",
            role=ParticipantRole.REQUIRED,
            timezone="America/Los_Angeles",
            working_hours=WorkingHours.with_lunch_break("9:00", "12:00", "13:00", "17:00")
        ),
        Participant(
            user_id="sf_dev",
            role=ParticipantRole.REQUIRED,
            timezone="America/Los_Angeles",
            working_hours=WorkingHours.from_string("8:00-16:00")
        ),
        
        # European team (2 people)
        Participant(
            user_id="london_lead",
            role=ParticipantRole.REQUIRED,
            timezone="Europe/London",
            working_hours=WorkingHours.with_lunch_break("9:00", "12:00", "13:00", "17:00")
        ),
        Participant(
            user_id="berlin_dev",
            role=ParticipantRole.OPTIONAL,
            timezone="Europe/Berlin",
            working_hours=WorkingHours.from_string("8:00-16:00")
        ),
        
        # Asia team (2 people)
        Participant(
            user_id="tokyo_lead",
            role=ParticipantRole.REQUIRED,
            timezone="Asia/Tokyo",
            working_hours=WorkingHours.with_lunch_break("9:00", "12:00", "13:00", "17:00")
        ),
        Participant(
            user_id="singapore_dev",
            role=ParticipantRole.OPTIONAL,
            timezone="Asia/Singapore",
            working_hours=WorkingHours.from_string("9:00-18:00")
        )
    ]
    return participants

def print_cost_breakdown(costs: SchedulingCosts, meeting: Meeting, time_range: TimeRange):
    """Print detailed cost breakdown for a meeting slot"""
    print("\nCost Breakdown:")
    print("-" * 30)
    
    for participant in meeting.participants:
        outside_cost = costs.outside_hours_cost(time_range, participant)
        time_cost = costs.time_of_day_cost(time_range.start, participant)
        consec_cost = costs.consecutive_meeting_cost(time_range, participant)
        
        print(f"\n{participant.user_id} ({participant.timezone}):")
        print(f"  Outside hours cost: {outside_cost:.2f}")
        print(f"  Time of day cost: {time_cost:.2f}")
        print(f"  Consecutive meeting cost: {consec_cost:.2f}")
        
        local_time = time_range.start.astimezone(participant.timezone)
        print(f"  Local time: {local_time.strftime('%I:%M %p')}")
    
    tz_cost = costs.timezone_span_cost(meeting.participants, time_range)
    print(f"\nTimezone span cost: {tz_cost:.2f}")
    
    total = costs.calculate_total_cost(time_range, meeting.participants)
    print(f"\nTotal cost: {total:.2f}")

def test_complex_scheduling():
    participants = create_test_participants()
    
    # Create a variety of meetings to test different scenarios
    meetings = [
        Meeting(
            title="All Hands (Everyone)",
            duration=timedelta(minutes=60),
            participants=participants,
            earliest_start=pytz.UTC.localize(datetime.now().replace(
                hour=14, minute=0, second=0, microsecond=0
            ))
        ),
        Meeting(
            title="US Team Only",
            duration=timedelta(minutes=45),
            participants=[p for p in participants 
                         if 'America' in str(p.timezone)],
            earliest_start=pytz.UTC.localize(datetime.now().replace(
                hour=15, minute=0, second=0, microsecond=0
            ))
        ),
        Meeting(
            title="NY-London Sync",
            duration=timedelta(minutes=30),
            participants=[
                next(p for p in participants if p.user_id == "ny_lead"),
                next(p for p in participants if p.user_id == "london_lead")
            ],
            earliest_start=pytz.UTC.localize(datetime.now().replace(
                hour=16, minute=0, second=0, microsecond=0
            ))
        ),
        Meeting(
            title="Cross-Continental (NY-Tokyo)",
            duration=timedelta(minutes=30),
            participants=[
                next(p for p in participants if p.user_id == "ny_lead"),
                next(p for p in participants if p.user_id == "tokyo_lead")
            ],
            earliest_start=pytz.UTC.localize(datetime.now().replace(
                hour=17, minute=0, second=0, microsecond=0
            ))
        ),
        Meeting(
            title="Early Morning Stand-up",
            duration=timedelta(minutes=15),
            participants=[p for p in participants 
                         if p.role == ParticipantRole.REQUIRED],
            earliest_start=pytz.UTC.localize(datetime.now().replace(
                hour=13, minute=0, second=0, microsecond=0
            ))
        )
    ]
    
    # In test_complex_scheduling function:
    costs = SchedulingCosts(
        outside_hours_base_cost=5.0,
        outside_hours_exp_factor=1.5,
        early_meeting_penalty=2.0,
        late_meeting_penalty=2.0,
        preferred_hour_bonus=-2.0,
        consecutive_meeting_penalty=1.0,
        timezone_span_penalty=0.5
    )
    
    scheduler = (SchedulerBuilder()
                .with_costs(costs)
                .with_time_increment(timedelta(minutes=30))  # Increased time increment for faster testing
                .build())
    
    # Schedule meetings
    scheduled = scheduler.schedule(meetings)
    
    # Print detailed results
    print("\nComplex Scheduling Test")
    print("=" * 50)
    
    for meeting in scheduled:
        print(f"\nMeeting: {meeting.title}")
        print("Participants:", ", ".join(p.user_id for p in meeting.participants))
        
        if meeting.scheduled_time:
            print(f"Status: SCHEDULED")
            print(f"UTC: {meeting.scheduled_time.start} - {meeting.scheduled_time.end}")
            
            # Print cost breakdown
            print_cost_breakdown(costs, meeting, meeting.scheduled_time)
            
            print("\nLocal times:")
            for p in meeting.participants:
                local_start = meeting.scheduled_time.start.astimezone(p.timezone)
                local_end = meeting.scheduled_time.end.astimezone(p.timezone)
                print(f"  {p.user_id}: {local_start.strftime('%I:%M %p')} - "
                      f"{local_end.strftime('%I:%M %p')} {p.timezone}")
        else:
            print("Status: FAILED TO SCHEDULE")
            
    # Print scheduling statistics
    print("\nScheduling Statistics")
    print("=" * 50)
    scheduled_count = sum(1 for m in scheduled if m.scheduled_time)
    print(f"Total meetings: {len(meetings)}")
    print(f"Successfully scheduled: {scheduled_count}")
    print(f"Failed to schedule: {len(meetings) - scheduled_count}")

if __name__ == "__main__":
    test_complex_scheduling()