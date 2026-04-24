"""
To-Do Manager Tool
Manages tasks/to-dos with local storage backend.
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)

# In-memory storage (in production, use a database)
todos_storage = []


class TodoManager:
    """Manage to-do items."""
    
    # Importance levels with humorous names
    IMPORTANCE_LEVELS = {
        "low": {
            "label": "Low",
            "name": "Second Breakfast",
            "description": "If it doesn't happen, we'll just eat again.",
            "color": "#BBBB00"  # Yellow
        },
        "medium": {
            "label": "Medium",
            "name": "The Beacons are Lit",
            "description": "Gondor calls for aid! (You should probably do this).",
            "color": "#FF6B35"  # Orange
        },
        "high": {
            "label": "High",
            "name": "One Does Not Simply Walk Away",
            "description": "This task is Sauron-level urgent. Do it now.",
            "color": "#DC143C"  # Crimson
        }
    }
    
    def __init__(self):
        self.todos = todos_storage
    
    async def add_todo(
        self,
        title: str,
        description: str,
        due_date: str,
        importance: str = "medium"
    ) -> Dict[str, Any]:
        """
        Add a new to-do item.
        
        Args:
            title: Title of the task
            description: Description of the task (max 200 words)
            due_date: Due date (ISO format)
            importance: Importance level (low, medium, high)
            
        Returns:
            Dictionary with created to-do
        """
        logger.info(f"Adding to-do: {title}")
        
        try:
            # Validate input
            if len(title.strip()) == 0:
                return {"status": "error", "error": "Title cannot be empty"}
            
            if len(description) > 200:
                return {"status": "error", "error": "Description exceeds 200 words limit"}
            
            if importance not in self.IMPORTANCE_LEVELS:
                importance = "medium"
            
            todo_item = {
                "id": len(self.todos) + 1,
                "title": title,
                "description": description,
                "due_date": due_date,
                "importance": importance,
                "importance_display": self.IMPORTANCE_LEVELS[importance],
                "completed": False,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            
            self.todos.append(todo_item)
            
            logger.info(f"To-do added successfully: {title}")
            
            return {
                "status": "success",
                "todo": todo_item
            }
            
        except Exception as e:
            logger.error(f"Error adding to-do: {str(e)}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    async def get_todos(self) -> Dict[str, Any]:
        """Get all to-do items."""
        logger.info(f"Fetching {len(self.todos)} to-dos...")
        
        return {
            "status": "success",
            "todos": self.todos,
            "count": len(self.todos)
        }
    
    async def update_todo(self, todo_id: int, **kwargs) -> Dict[str, Any]:
        """Update a to-do item."""
        logger.info(f"Updating to-do: {todo_id}")
        
        try:
            for todo in self.todos:
                if todo["id"] == todo_id:
                    for key, value in kwargs.items():
                        if key in todo:
                            todo[key] = value
                    
                    todo["updated_at"] = datetime.now().isoformat()
                    
                    logger.info(f"To-do updated: {todo_id}")
                    return {"status": "success", "todo": todo}
            
            return {"status": "error", "error": "To-do not found"}
            
        except Exception as e:
            logger.error(f"Error updating to-do: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    async def delete_todo(self, todo_id: int) -> Dict[str, Any]:
        """Delete a to-do item."""
        logger.info(f"Deleting to-do: {todo_id}")
        
        try:
            self.todos[:] = [todo for todo in self.todos if todo["id"] != todo_id]
            
            logger.info(f"To-do deleted: {todo_id}")
            
            return {
                "status": "success",
                "message": f"To-do {todo_id} deleted"
            }
            
        except Exception as e:
            logger.error(f"Error deleting to-do: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    async def complete_todo(self, todo_id: int) -> Dict[str, Any]:
        """Mark a to-do as complete."""
        logger.info(f"Completing to-do: {todo_id}")
        
        return await self.update_todo(todo_id, completed=True)
    
    def get_empty_state_message(self) -> str:
        """Get a humorous empty state message."""
        messages = [
            "Your life is suspiciously organized... let's fix that.",
            "A clean list is the playground of a procrastinator. Add something!",
            "No tasks? Are you actually working? 🤔",
            "Empty list = Empty mind? Time to add something! 🧠",
            "Congratulations! You've achieved the impossible. Nothing to do. 🎉",
            "Boredom detected. Quick, add a task before it's too late! ⚡",
            "Plot twist: You forgot to add your tasks. Add them now! 📝"
        ]
        
        import random
        return random.choice(messages)


def create_todo_manager():
    """Factory function to create TodoManager instance."""
    return TodoManager()
