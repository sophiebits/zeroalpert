import datetime
import functools
import hmac
import os

from google.appengine.ext import ndb
import jinja2
import webapp2

import models
import secrets

# TODO(alpert): Make an App.root-esque global
_jinja_env = jinja2.Environment(
        autoescape=True,
        loader=jinja2.FileSystemLoader(
                os.path.join(os.path.dirname(__file__), 'templates')),
    )


def _make_cookie_signature(key, value):
    """Return a hex string corresponding to a signature for (key, value)."""
    sig = hmac.new(secrets.token_recipe_key)
    # TODO(alpert): How secure is this really?
    sig.update(key + '|' + value)
    return sig.hexdigest()


def _set_signed_cookie(handler, key, value):
    sig = _make_cookie_signature(key, value)
    expires = datetime.datetime.now() + datetime.timedelta(days=365)

    handler.response.set_cookie(key, value, expires=expires)
    handler.response.set_cookie(key + '_sig', sig, expires=expires)


def _get_signed_cookie(handler, key):
    value = handler.request.cookies.get(key)
    value_sig = handler.request.cookies.get(key + '_sig')
    if value and value_sig:
        sig = _make_cookie_signature(key, value)

        if _secure_eq(sig, value_sig):
            return value


def _secure_eq(s1, s2):
    if len(s1) != len(s2):
        return False
    x = 0
    for c1, c2 in zip(s1, s2):
        x |= (ord(c1) ^ ord(c2))
    return x == 0


def login_required(func):
    @functools.wraps(func)
    def wrapped(handler, *args):
        user_data = handler.get_current_user()
        if not user_data:
            handler.error(401)
            handler.response.out.write('401 Unauthorized')
            return
        return func(handler, *args)
    return wrapped


class RequestHandler(webapp2.RequestHandler):
    def get_current_user(self):
        # TODO(alpert): This doesn't cache properly if the UserData has been
        # deleted from the datastore
        if self._current_user_id and not hasattr(self, '_current_user'):
            self._current_user = models.UserData.get_by_id(
                    self._current_user_id)

        return self._current_user

    def dispatch(self):
        zaid = _get_signed_cookie(self, 'zaid')
        if zaid is not None:
            self._current_user_id = int(zaid)
        else:
            self._current_user_id = None
            self._current_user = None

        return super(RequestHandler, self).dispatch()


class Login(RequestHandler):
    def get(self):
        # TODO(alpert): Remove duplication with _get_signed_cookie
        zaid = self.request.get('zaid', None)
        zaid_sig = self.request.get('zaid_sig', None)
        cont = self.request.get('continue', '/')

        if zaid and zaid_sig and cont.startswith('/'):
            sig = _make_cookie_signature('zaid', zaid)
            if _secure_eq(sig, zaid_sig):
                _set_signed_cookie(self, 'zaid', zaid)
                self.redirect(cont)
                return

        self.error(400)
        self.response.out.write('Invalid signature')


class ViewMeal(RequestHandler):
    @login_required
    @ndb.toplevel
    def get(self, meal_id):
        @ndb.tasklet
        def get_feedback_author_async(feedback):
            author = yield feedback.key.parent().get_async()
            raise ndb.Return((feedback, author))

        meal = models.Meal.get_by_id(meal_id)

        if meal is None:
            self.error(404)
            self.response.headers['Content-Type'] = 'text/plain'
            self.response.out.write("Meal %r not found" % meal_id)

        dishes = models.Dish.query(ancestor=meal.key).fetch(1000)

        # TODO(alpert): HRD consistency
        feedback = models.Feedback.query().filter(
                models.Feedback.meal == meal.key).fetch(1000)
        feedback_with_authors = yield [
                get_feedback_author_async(f) for f in feedback]

        tmpl = _jinja_env.get_template('viewmeal.html')
        self.response.out.write(tmpl.render({
                'user_data': self.get_current_user(),
                'meal': meal,
                'dishes': dishes,
                'feedback_with_authors': feedback_with_authors,
            }))


class PostMealFeedback(RequestHandler):
    @login_required
    def post(self, meal_id):
        meal = models.Meal.get_by_id(meal_id)

        if meal is None:
            self.error(404)
            self.response.headers['Content-Type'] = 'text/plain'
            self.response.out.write("Meal %r not found" % meal_id)

        stars = int(self.request.get('stars'))
        assert 1 <= stars <= 5
        text = self.request.get('text')

        user_data = self.get_current_user()

        @ndb.transactional
        def txn():
            f = models.Feedback.get_by_id(meal_id, parent=user_data.key)
            if not f:
                f = models.Feedback(
                        id=meal_id,
                        parent=user_data.key,
                        meal=meal.key,
                    )
            f.stars = stars
            f.text = text
            f.put()
        txn()

        self.redirect("/meals/%s" % meal_id)


app = webapp2.WSGIApplication([
    ('/meals/([0-9a-f]+)', ViewMeal),
    ('/meals/([0-9a-f]+)/feedback', PostMealFeedback),
    ('/login', Login),
], debug=True)
