import json

class TodoApp:
    def __init__(self, storage_file='tasks.json'):
        self.tasks = []
        self.storage_file = storage_file
        self.load_tasks()

    def add_task(self, task):
        self.tasks.append({'task': task, 'completed': False})
        self.save_tasks()

    def remove_task(self, task_index):
        if 0 <= task_index < len(self.tasks):
            del self.tasks[task_index]
            self.save_tasks()

    def list_tasks(self):
        return [f"[{ '✓' if task['completed'] else ' ' }] {task['task']}" for task in self.tasks]

    def mark_complete(self, task_index):
        if 0 <= task_index < len(self.tasks):
            self.tasks[task_index]['completed'] = True
            self.save_tasks()

    def save_tasks(self):
        with open(self.storage_file, 'w') as f:
            json.dump(self.tasks, f)

    def load_tasks(self):
        try:
            with open(self.storage_file, 'r') as f:
                self.tasks = json.load(f)
        except FileNotFoundError:
            self.tasks = []

if __name__ == '__main__':
    app = TodoApp()
    # Example usage:
    app.add_task('Buy groceries')
    app.add_task('Write code')
    print(app.list_tasks())
    app.mark_complete(1)
    print(app.list_tasks())
    app.remove_task(0)
    print(app.list_tasks())