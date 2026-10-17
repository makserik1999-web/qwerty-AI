"""Quizzes: a service of its own.

Everything a quiz needs that is not generation lives here - the quizzes a
teacher keeps, the sessions they open, the students who join one with a code,
their answers and what those answers add up to. It runs as its own container
with its own collections, and it shares nothing with the backend's code.

Two things it takes from elsewhere, each across a deliberate seam:

  WHO A TEACHER IS comes from the backend, which owns accounts and sessions.
  This service asks it (identity.py) instead of reading its tables, so the
  account schema can change without this service noticing.

  WRITING QUESTIONS is the agent's job, reached through the backend like every
  other generated document. The editor asks the backend for a draft and saves
  the result here; nothing in this service holds a model key or waits on one.

Students do not need an account. A quiz is joined with a six-character code,
which exists only while the teacher keeps the session open, and everything a
student can do from there is bounded by that session.
"""
