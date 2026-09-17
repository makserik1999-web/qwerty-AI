END = "END"


class StateGraph:
    def __init__(self, *a, **k):
        self.nodes = {}
        self.edges = []

    def add_node(self, name, fn):
        self.nodes[name] = fn

    def add_parallel_group(self, *a, **k):
        pass

    def set_entry_point(self, name):
        self.entry = name

    def add_edge(self, a, b):
        self.edges.append((a, b))

    def add_conditional_edges(self, *a, **k):
        self.edges.append(a)

    def compile(self):
        return self