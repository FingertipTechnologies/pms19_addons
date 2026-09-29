## Module <activity_dashboard_mngmnt>

#### 19.04.2025
#### Version 18.0.1.0.0
##### ADD
- Initial commit for Activity Management

#### 29.09.2026
#### Version 19.0.1.2.0
##### FIX
- Sales Users could not pick anyone but themselves in "Assigned to" when scheduling an activity: the res.users rule limiting them to their own user record is removed.
- Sales Users can now assign an activity to a colleague: the mail.activity rule covers activities assigned to them or scheduled by them, so the create check and the re-read after Save no longer fail.
