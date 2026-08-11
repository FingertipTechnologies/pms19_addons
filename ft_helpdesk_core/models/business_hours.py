from odoo import api, fields, models
from datetime import timedelta
import pytz


class HelpdeskBusinessHours(models.Model):
    _name = 'ft.helpdesk.business.hours'
    _description = 'Helpdesk Business Hours'
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=True)
    active = fields.Boolean(default=True)
    timezone = fields.Selection(
        '_tz_get', string='Timezone', required=True,
        default=lambda self: self.env.user.tz or 'UTC',
    )
    line_ids = fields.One2many(
        'ft.helpdesk.business.hours.line', 'business_hours_id',
        string='Working Hours',
    )
    holiday_ids = fields.One2many(
        'ft.helpdesk.business.hours.holiday', 'business_hours_id',
        string='Holidays',
    )

    @api.model
    def _tz_get(self):
        return [(tz, tz) for tz in sorted(pytz.all_timezones_set)]

    def _is_working_time(self, dt):
        """Check if a datetime falls within business hours."""
        self.ensure_one()
        tz = pytz.timezone(self.timezone)
        local_dt = dt.astimezone(tz)
        # Check holidays
        date_str = local_dt.date()
        for holiday in self.holiday_ids:
            if holiday.date_from <= date_str <= holiday.date_to:
                return False
        # Check working hours
        weekday = str(local_dt.weekday())
        time_float = local_dt.hour + local_dt.minute / 60.0
        for line in self.line_ids:
            if line.day_of_week == weekday:
                if line.hour_from <= time_float <= line.hour_to:
                    return True
        return False

    def _add_business_hours(self, start_dt, hours):
        """Add business hours to a datetime, skipping non-working time."""
        self.ensure_one()
        remaining_minutes = hours * 60
        current = start_dt
        while remaining_minutes > 0:
            if self._is_working_time(current):
                remaining_minutes -= 1
                current += timedelta(minutes=1)
            else:
                current += timedelta(minutes=1)
        return current


class HelpdeskBusinessHoursLine(models.Model):
    _name = 'ft.helpdesk.business.hours.line'
    _description = 'Business Hours Line'
    _order = 'day_of_week, hour_from'

    business_hours_id = fields.Many2one(
        'ft.helpdesk.business.hours', string='Business Hours',
        required=True, ondelete='cascade',
    )
    day_of_week = fields.Selection([
        ('0', 'Monday'),
        ('1', 'Tuesday'),
        ('2', 'Wednesday'),
        ('3', 'Thursday'),
        ('4', 'Friday'),
        ('5', 'Saturday'),
        ('6', 'Sunday'),
    ], string='Day of Week', required=True)
    hour_from = fields.Float(string='From', required=True, default=9.0)
    hour_to = fields.Float(string='To', required=True, default=17.0)


class HelpdeskBusinessHoursHoliday(models.Model):
    _name = 'ft.helpdesk.business.hours.holiday'
    _description = 'Business Hours Holiday'
    _order = 'date_from'

    business_hours_id = fields.Many2one(
        'ft.helpdesk.business.hours', string='Business Hours',
        required=True, ondelete='cascade',
    )
    name = fields.Char(string='Holiday Name', required=True, translate=True)
    date_from = fields.Date(string='From', required=True)
    date_to = fields.Date(string='To', required=True)
