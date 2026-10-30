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

## Monthly feedback requests (email)
- Project form > **Customer Feedback** tab: enable *Monthly Customer Feedback*
  and choose the feedback contacts (contacts of the project customer).
- On the 1st of every month (03:30 UTC / 09:00 IST) a cron creates one
  request per enabled, active project for the previous month (from
  *Settings > First Month to Request* on) and emails each contact a
  project-specific link `/my/feedback?request=<token>`. A missed 1st is run
  as soon as the scheduler is back. This is the only cron of the module: the
  email status of each contact (Queued -> Sent / Failed) is updated by the
  mail queue itself when it sends the email.
- **Customer Feedback > Monthly Requests**: requests with per-contact email
  status (Pending / Queued / Sent / Failed / Skipped), *Send Now* and
  *Retry Failed*. A channel already sent is never resent.
- WhatsApp sending is provided by the separate module
  `ft_customer_feedback_whatsapp` (install it once the WhatsApp gateway is
  configured).

## Changelog
- **19.0.2.3.1**: no daily cron; email statuses are updated by the mail
  queue when the email is sent. A migration removes the *Synchronise Request
  Status* cron.
- **19.0.2.3.0**: monthly request cron runs on the 1st of every month instead
  of daily. A migration updates the existing cron record.
- **19.0.2.1.0**: WhatsApp moved to `ft_customer_feedback_whatsapp`; no more
  dependency on `mail_gateway_whatsapp` / `ft_message_tracking`. Email-only
  sending with channel extension hooks on `ft.feedback.request.recipient`:
  `_ft_send_channels`, `_ft_send_channel`, `_ft_channel_states`,
  `_ft_channel_done_states`, `_ft_sync_channel_states`,
  `_ft_cron_sync_channel_states`.
- **19.0.2.0.0**: monthly customer feedback requests (email + WhatsApp).
