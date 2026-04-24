"""
Schedule Email Tool
Schedule event reminders via email using APScheduler and SMTP.
"""

import logging
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Any
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

# Global scheduler
scheduler = BackgroundScheduler()
if not scheduler.running:
    scheduler.start()


class EmailScheduler:
    """Schedule event reminders via email."""
    
    def __init__(self, email_sender: str, email_password: str):
        self.email_sender = email_sender
        self.email_password = email_password
        self.scheduler = scheduler
        self.scheduled_jobs = {}
    
    async def schedule_event_reminder(
        self,
        event_title: str,
        event_time: str,
        event_description: str,
        recipient_email: str,
        reminder_minutes_before: int = 15
    ) -> Dict[str, Any]:
        """
        Schedule an event reminder email.
        
        Args:
            event_title: Title of the event
            event_time: Time of the event (ISO format)
            event_description: Description of the event
            recipient_email: Email to send reminder to
            reminder_minutes_before: Minutes before event to send reminder
            
        Returns:
            Dictionary with scheduling confirmation
        """
        logger.info(f"Scheduling email reminder for: {event_title}")
        
        try:
            event_datetime = datetime.fromisoformat(event_time)
            
            # Schedule the email
            job_id = f"event_{event_title}_{event_datetime.timestamp()}"
            
            self.scheduler.add_job(
                self._send_reminder_email,
                'date',
                run_date=event_datetime,
                args=[event_title, event_description, recipient_email, event_datetime],
                id=job_id,
                replace_existing=True
            )
            
            self.scheduled_jobs[job_id] = {
                "title": event_title,
                "time": event_time,
                "recipient": recipient_email
            }
            
            logger.info(f"Email reminder scheduled for {event_title}")
            
            return {
                "status": "scheduled",
                "event_title": event_title,
                "event_time": event_time,
                "job_id": job_id,
                "message": f"Don't worry, I'll nag you via email when it's time. 📬"
            }
            
        except Exception as e:
            logger.error(f"Error scheduling email: {str(e)}")
            return {
                "status": "error",
                "error": str(e),
                "event_title": event_title
            }
    
    def _send_reminder_email(self, event_title: str, description: str, recipient: str, event_time: datetime):
        """Send the reminder email (internal method)."""
        try:
            logger.info(f"Sending reminder email for: {event_title}")
            
            # Create email
            msg = MIMEMultipart()
            msg['From'] = self.email_sender
            msg['To'] = recipient
            msg['Subject'] = f"⏰ Reminder: {event_title}"
            
            body = f"""
            Hi there!

            This is your reminder for:
            
            📌 Event: {event_title}
            🕐 Time: {event_time.strftime('%Y-%m-%d %H:%M:%S')}
            📝 Details: {description}
            
            Don't be late! 🚀
            
            ---
            Gandalf the Organizer
            Your AI Personal Assistant
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            # Send email
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(self.email_sender, self.email_password)
                server.send_message(msg)
            
            logger.info(f"Email sent successfully to {recipient}")
            
        except Exception as e:
            logger.error(f"Error sending email: {str(e)}")
    
    async def get_scheduled_events(self) -> Dict[str, Any]:
        """Get all scheduled events."""
        logger.info("Fetching scheduled events...")
        
        return {
            "status": "success",
            "scheduled_events": self.scheduled_jobs,
            "count": len(self.scheduled_jobs)
        }
    
    async def cancel_event_reminder(self, job_id: str) -> Dict[str, Any]:
        """Cancel a scheduled event reminder."""
        logger.info(f"Canceling event reminder: {job_id}")
        
        try:
            if job_id in self.scheduled_jobs:
                self.scheduler.remove_job(job_id)
                del self.scheduled_jobs[job_id]
                
                logger.info(f"Event reminder canceled: {job_id}")
                
                return {
                    "status": "canceled",
                    "job_id": job_id
                }
            else:
                return {
                    "status": "error",
                    "error": "Job not found"
                }
        except Exception as e:
            logger.error(f"Error canceling event: {str(e)}")
            return {
                "status": "error",
                "error": str(e)
            }


def create_email_scheduler(email_sender: str, email_password: str):
    """Factory function to create EmailScheduler instance."""
    return EmailScheduler(email_sender, email_password)
