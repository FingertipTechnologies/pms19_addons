# FT Customer Feedback

Configurable customer feedback survey for the customer portal.

## Backend (Customer Feedback app)
- **Feedback Questions**: one line per question. Subject + answer type
  (Rating 1-5 smileys / Score 0-10 / Free Text), optional section, required
  flag, drag-and-drop ordering. Archive a question to hide it from the portal.
- **Configuration > Sections**: the green headings that group questions.
- **Configuration > Settings**: introduction and thank-you texts.
- **Responses**: one record per submission with status (Draft / Submitted),
  date, customer, portal user and one answer line per question (number or free text). Pivot/graph views.
- **Reporting**: Customer-wise Feedback, Question-wise Analysis, Average
  Ratings and Feedback Trends. Built on a read-only SQL view that only
  includes submitted responses and answered questions; ratings (1-5) and
  scores (0-10) are separate measures and every figure is an average.
- Each answer line stores the question text and type as asked, so editing a
  question later does not rewrite historical feedback. Resetting a response
  to draft and submitting it again keeps the original submission date.

Groups: *Customer Feedback / User* (read responses) and *Manager* (configure).

## Portal
Logged-in customers get an orange **Feedback** button in the support portal
header (`/my/feedback`). Submitting creates a Response and shows a thank-you
page. A **Feedbacks** tab after Knowledge Base (`/my/feedbacks`) lists every
feedback the customer's company has given, each opening to its answers.
