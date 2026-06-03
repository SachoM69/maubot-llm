class LlmCancellationToken():
    def __init__(self):
        self.cancellation_requested = False
        self.dependent_query = None

    def set_query(self, query):
        self.dependent_query = query

    def cancel(self):
        if (self.dependent_query):
            self.dependent_query.cancel()
        self.cancellation_requested = True

    def is_cancellation_requested(self):
        return self.cancellation_requested