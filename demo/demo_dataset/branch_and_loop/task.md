# Branch and Loop

Alex is a PhD student studying reinforcement learning. His personal assistant agent helps him prepare for an upcoming RL final exam by managing email, calendar, Notion, and workspace.

## Capabilities

email, notion, calendar

## Task Flow

### Stage 0: Check email and create calendar event

Prof. Zhang sends Alex an exam reminder email (June 20, 2025). The agent reads the email and creates a calendar event with the correct date, time, and location.

### Stage 1: Organize study notes

Alex's lecture notes (6 markdown files) are in the workspace. The agent reads them and writes a consolidated study guide in a Notion page. If the guide is too brief, the agent is asked to expand it — this repeats until the content reaches 5x its original length, or up to 5 attempts.

### Stage 2: Branch based on note quality

The task checks whether the study guide mentions "Bellman equation" (a core RL concept).

**If yes (Stage 2a):** Alex is well prepared. A new email arrives from Prof. Zhang — the exam has been rescheduled to June 23. The agent reads the email and updates the calendar event.

**If no (Stage 2b):** Alex is not prepared. The agent sends an email to Prof. Zhang requesting a deadline extension.

## Checkers


| Check                    | Stage | What it verifies                                                       |
| ------------------------ | ----- | ---------------------------------------------------------------------- |
| `calendar_event_created` | 0     | Calendar has an exam event in June 2025                                |
| `notes_created`          | 1     | Notion study guide has more than 100 characters                        |
| `all_topics_covered`     | 1     | Study guide mentions MDP, Policy Gradient, Q-Learning, and Model-Based |
| `calendar_updated`       | 2a    | Calendar event moved to June 23                                        |
| `delay_email_sent`       | 2b    | Email sent to Prof. Zhang's inbox                                      |


