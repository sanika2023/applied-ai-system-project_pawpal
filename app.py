import streamlit as st
from pawpal_system import Owner, Pet, Task, TaskStatus, Schedule, Scheduler, ScheduleEntry
from datetime import date, time
import pandas as pd
from huggingface_hub import InferenceClient
from dotenv import load_dotenv
import os

load_dotenv()


def _build_agent_context(owner, target_date):
    lines = [
        f"Owner: {owner.name}",
        f"Available time per day: {owner.available_time_per_day} minutes",
        f"Schedule date: {target_date}",
        "",
    ]
    for pet in owner.pets:
        lines.append(f"Pet: {pet.name} ({pet.type}, age {pet.age})")
        pending = pet.get_pending_tasks(target_date)
        if pending:
            lines.append(f"  Pending tasks ({len(pending)}):")
            for t in pending:
                priority_label = ["High", "Medium", "Low"][t.priority - 1]
                recur = f", recurs {t.recurrence}" if t.recurrence else ""
                window = (
                    f", preferred {t.preferred_window[0].strftime('%H:%M')}-{t.preferred_window[1].strftime('%H:%M')}"
                    if t.preferred_window else ""
                )
                lines.append(f"    - {t.name} ({t.type}, {t.duration_minutes}min, {priority_label} priority{recur}{window})")
        else:
            lines.append("  No pending tasks")
        lines.append("")
    return "\n".join(lines)


def _run_ai_agent(api_key: str, context: str, user_request: str) -> tuple:
    """2-step agentic loop: draft a plan, then self-check and revise. Returns (plan, final)."""
    client = InferenceClient(
        token=api_key,
    )
    system = (
        "You are PawPal+, an intelligent pet care scheduling assistant. "
        "You help owners plan optimal daily care schedules by analyzing tasks, "
        "detecting issues, and providing clear, actionable recommendations."
    )

    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"Current pet care data:\n\n{context}\n\n"
                f"Request: {user_request}\n\n"
                "Step 1 — Draft an initial daily schedule plan."
            ),
        },
    ]
    model = "meta-llama/Llama-3.3-70B-Instruct"
    r1 = client.chat_completion(model=model, messages=messages, max_tokens=1024)
    plan = r1.choices[0].message.content

    messages.append({"role": "assistant", "content": plan})
    messages.append({
        "role": "user",
        "content": (
            "Step 2 — Review your plan and check: "
            "(1) Does total task time fit within the owner's available time? "
            "(2) Are any essential care types missing for each pet? "
            "(3) Are there any conflicts or gaps? "
            "Revise if needed and provide your final recommendation."
        ),
    })
    r2 = client.chat_completion(model=model, messages=messages, max_tokens=1024)
    return plan, r2.choices[0].message.content

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="wide")

st.title("🐾 PawPal+ Smart Scheduler")

st.markdown(
    """
Welcome to PawPal+, your intelligent pet care planning assistant.

This app helps you organize pet care tasks, detect scheduling conflicts, and build optimized daily schedules.
"""
)

with st.expander("About PawPal+", expanded=False):
    st.markdown(
        """
**PawPal+** uses intelligent scheduling to help you:
- **Organize tasks** by priority and preferred time windows
- **Sort chronologically** — tasks are automatically arranged by when they should happen
- **Detect conflicts** — overlapping tasks trigger smart warnings
- **Manage recurrence** — daily/weekly tasks auto-generate new instances
- **Validate capacity** — warns if tasks exceed your available time
        """
    )

st.divider()

# Initialize Owner in session state if it doesn't exist
if 'scheduler' not in st.session_state:
    st.session_state.scheduler = Scheduler()

scheduler = st.session_state.scheduler

col1, col2 = st.columns(2)

with col1:
    st.subheader("👤 Owner Setup")
    owner_name = st.text_input("Owner name", value="Jordan", key="owner_name_input")
    available_time = st.slider("Available time per day (minutes)", min_value=60, max_value=1440, value=480)
    
    if owner_name:
        if 'owner' not in st.session_state:
            st.session_state.owner = Owner(name=owner_name, available_time_per_day=available_time, preferences={}, pets=[])
        owner = st.session_state.owner
        owner.available_time_per_day = available_time  # Update available time
        st.success(f"Owner: **{owner.name}** | Available: **{available_time}** min/day")
    else:
        owner = None

with col2:
    st.subheader("🐾 Pet Management")
    if owner:
        pet_name = st.text_input("New pet name", value="Mochi", key="pet_name_input")
        species = st.selectbox("Species", ["dog", "cat", "rabbit", "bird", "other"])
        age = st.number_input("Age (years)", min_value=0, max_value=30, value=1)
        
        if st.button("➕ Add Pet", use_container_width=True):
            if pet_name and not any(p.name == pet_name for p in owner.pets):
                pet = Pet(name=pet_name, type=species, age=age, needs={}, owner=owner, tasks=[])
                owner.add_pet(pet)
                st.success(f"✓ Added **{pet_name}** the {species}!")
                st.rerun()
            elif any(p.name == pet_name for p in owner.pets):
                st.warning(f"⚠️ **{pet_name}** already exists!")

st.divider()

# Display current pets
if owner and owner.pets:
    st.markdown("### Current Pets")
    pet_cols = st.columns(len(owner.pets))
    for idx, pet in enumerate(owner.pets):
        with pet_cols[idx]:
            st.info(f"""
            🐾 **{pet.name}**
            - Type: {pet.type}
            - Age: {pet.age} years
            - Tasks: {len(pet.tasks)}
            - Pending: {len(pet.get_pending_tasks(date.today()))}
            """)
elif owner:
    st.info("👆 Add a pet above to get started!")
else:
    st.warning("👈 Enter an owner name first!")

st.divider()

# Task Management
if owner and owner.pets:
    st.markdown("### 📋 Task Management")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        selected_pet_name = st.selectbox("Select pet for task", [p.name for p in owner.pets], key="pet_select")
        selected_pet = next(p for p in owner.pets if p.name == selected_pet_name)
    
    with col2:
        st.write("")  # spacer
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        task_title = st.text_input("Task title", value="Morning walk", key="task_title_input")
    with col2:
        duration = st.number_input("Duration (min)", min_value=1, max_value=240, value=20, key="duration_input")
    with col3:
        priority_map = {"🔴 High": 1, "🟡 Medium": 2, "🟢 Low": 3}
        priority_label = st.selectbox("Priority", list(priority_map.keys()), index=1, key="priority_select")
        priority = priority_map[priority_label]
    with col4:
        task_type = st.selectbox("Type", ["exercise", "feeding", "grooming", "bathing", "training", "playtime", "medical", "medication", "enrichment", "socialization", "other"], key="type_select")
    with col5:
        recurrence = st.selectbox("Recurrence", ["none", "daily", "weekly"], key="recur_select")
    
    add_task_cols = st.columns([2, 1])
    with add_task_cols[0]:
        if st.button("➕ Add Task", use_container_width=True):
            new_task = Task(
                id=f"{selected_pet.name}_{len(selected_pet.tasks) + 1}",
                name=task_title,
                type=task_type,
                duration_minutes=int(duration),
                priority=priority,
                deadline=None,
                recurrence=None if recurrence == "none" else recurrence,
                preferred_window=None,
                status=TaskStatus.PENDING,
                pet=selected_pet
            )
            selected_pet.add_task(new_task)
            st.success(f"✓ Added **{task_title}** to {selected_pet.name}!")
            st.rerun()
    
    with add_task_cols[1]:
        if st.button("🔄 Mark Task Done", use_container_width=True):
            pending_tasks = [t for t in selected_pet.tasks if t.status == TaskStatus.PENDING]
            if pending_tasks:
                task_to_mark = pending_tasks[0]
                task_to_mark.mark_done()
                st.success(f"✓ Marked **{task_to_mark.name}** as done!")
                if task_to_mark.recurrence:
                    st.info(f"📅 Next {task_to_mark.recurrence} instance auto-created!")
                st.rerun()
            else:
                st.warning("No pending tasks to mark complete.")
    
    # Display ALL tasks for each pet with filtering
    st.markdown("### View & Manage Tasks")
    
    for pet in owner.pets:
        if pet.tasks:
            with st.expander(f"📌 {pet.name}'s Tasks ({len(pet.tasks)} total)", expanded=True):
                # Filter options
                filter_cols = st.columns(3)
                with filter_cols[0]:
                    filter_status = st.multiselect("Status", [s.value for s in TaskStatus], default=[TaskStatus.PENDING.value, TaskStatus.DONE.value], key=f"{pet.name}_status_filter")
                with filter_cols[1]:
                    task_types = list(set(t.type for t in pet.tasks))
                    filter_type = st.multiselect("Type", task_types, default=task_types, key=f"{pet.name}_type_filter")
                with filter_cols[2]:
                    sort_option = st.radio("Sort by", ["Priority", "Time Window", "Duration"], key=f"{pet.name}_sort", horizontal=True)
                
                # Apply filters
                filtered_tasks = scheduler.filter_tasks(
                    pet.tasks,
                    pet_name=pet.name,
                    status=None,  # Filter manually below
                    task_type=None
                )
                filtered_tasks = [t for t in filtered_tasks if t.status.value in filter_status and t.type in filter_type]
                
                # Apply sorting
                if sort_option == "Time Window":
                    filtered_tasks = scheduler.sort_by_time(filtered_tasks)
                elif sort_option == "Priority":
                    filtered_tasks = sorted(filtered_tasks, key=lambda t: t.priority)
                elif sort_option == "Duration":
                    filtered_tasks = sorted(filtered_tasks, key=lambda t: t.duration_minutes, reverse=True)
                
                # Display as table
                if filtered_tasks:
                    task_df = pd.DataFrame([
                        {
                            "Task": t.name,
                            "Type": t.type,
                            "Duration (min)": t.duration_minutes,
                            "Priority": ["🔴 High", "🟡 Medium", "🟢 Low"][t.priority - 1],
                            "Status": "✓ Done" if t.status == TaskStatus.DONE else "⏳ Pending",
                            "Window": f"{t.preferred_window[0].strftime('%H:%M')}-{t.preferred_window[1].strftime('%H:%M')}" if t.preferred_window else "Flexible",
                            "Recurs": t.recurrence or "—"
                        }
                        for t in filtered_tasks
                    ])
                    st.dataframe(task_df, use_container_width=True, hide_index=True)
                else:
                    st.info(f"No tasks match your filters.")

st.divider()

# Schedule Generation with Smart Features
st.markdown("## 📅 Smart Schedule Generator")

if owner and owner.pets:
    schedule_cols = st.columns([2, 1, 1])
    
    with schedule_cols[0]:
        target_date = st.date_input("Schedule date", value=date.today())
    
    with schedule_cols[1]:
        if st.button("🔨 Generate Schedule", use_container_width=True):
            st.session_state.generate_schedule = True
        else:
            st.session_state.generate_schedule = st.session_state.get("generate_schedule", False)
    
    with schedule_cols[2]:
        st.write("")  # spacer
    
    if st.session_state.generate_schedule and owner:
        # Count pending tasks
        total_pending = sum(len(p.get_pending_tasks(target_date)) for p in owner.pets)
        
        if total_pending > 0:
            schedule = owner.plan_daily_schedule(target_date)
            
            # Display capacity check
            st.markdown("### ⏱️ Capacity Analysis")
            capacity_cols = st.columns(3)
            with capacity_cols[0]:
                st.metric("Total Time Needed", f"{schedule.total_duration} min")
            with capacity_cols[1]:
                st.metric("Available Time", f"{owner.available_time_per_day} min")
            with capacity_cols[2]:
                remaining = owner.available_time_per_day - schedule.total_duration
                if remaining >= 0:
                    st.success(f"✓ {remaining} min available")
                else:
                    st.warning(f"⚠️ {abs(remaining)} min over capacity!")
            
            # Display schedule as formatted table
            st.markdown("### 📋 Today's Schedule")
            schedule_df = pd.DataFrame([
                {
                    "Time": f"{e.start_time.strftime('%H:%M')} — {e.end_time.strftime('%H:%M')}",
                    "Pet": e.task.pet.name,
                    "Task": e.task.name,
                    "Type": e.task.type,
                    "Duration": f"{e.task.duration_minutes} min"
                }
                for e in schedule.entries
            ])
            st.dataframe(schedule_df, use_container_width=True, hide_index=True)
            
            # Display conflict warnings
            if schedule.conflict_info and schedule.conflict_info.get("has_conflicts"):
                st.markdown("### ⚠️ Scheduling Conflicts Detected")
                for warning in schedule.conflict_info.get("warning_messages", []):
                    st.warning(warning)
            else:
                st.success("✓ No scheduling conflicts detected!")
            
            # Display explanation
            st.markdown("### 💡 Schedule Explanation")
            explanation_text = owner.explain_schedule(schedule)
            st.info(explanation_text)
        else:
            st.warning("📭 No pending tasks for the selected date. Add tasks to your pets first!")
else:
    st.info("👈 Set up at least one pet with tasks to generate a schedule.")

st.divider()

# AI Agent Section
st.markdown("## 🤖 AI Schedule Assistant")
st.markdown(
    "Describe what you need and the AI agent will **plan**, **self-check**, and **revise** "
    "a care schedule recommendation for you."
)

if owner and owner.pets:
    api_key = os.environ.get("HF_API_KEY", "")
    if not api_key:
        st.error("HF_API_KEY not found. Add it to your .env file and restart the app.")
        st.stop()

    ai_request = st.text_area(
        "What would you like the AI agent to do?",
        value="Analyze my pets' current tasks and suggest an optimized daily care schedule. Flag any gaps or issues.",
        key="ai_request_input",
    )

    if st.button("🤖 Run AI Agent", key="run_agent_btn"):
        if not api_key:
            st.warning("Please provide an Anthropic API key.")
        else:
            context = _build_agent_context(owner, date.today())
            with st.spinner("Agent is planning and self-checking..."):
                try:
                    plan, final = _run_ai_agent(api_key, context, ai_request)
                    st.session_state.agent_plan = plan
                    st.session_state.agent_final = final
                except Exception as e:
                    st.error(f"Agent error: {e}")

    if st.session_state.get("agent_plan"):
        with st.expander("Step 1 — Initial Plan (Agent's Draft)", expanded=False):
            st.markdown(st.session_state.agent_plan)
    if st.session_state.get("agent_final"):
        st.markdown("### Final Recommendation")
        st.markdown(st.session_state.agent_final)
else:
    st.info("👈 Set up at least one pet with tasks to use the AI assistant.")
