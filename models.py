from google.appengine.ext import ndb


class UserData(ndb.Model):
    full_name = ndb.StringProperty(indexed=False, required=True)


class Meal(ndb.Model):
    title = ndb.StringProperty(indexed=False, required=True)
    dt = ndb.DateTimeProperty(indexed=True, required=True)


class Dish(ndb.Model):
    # corresponding Meal as db parent
    title = ndb.StringProperty(indexed=False, required=True)


class Feedback(ndb.Model):
    # author UserData as db parent
    meal = ndb.KeyProperty(indexed=True, required=True)
    stars = ndb.IntegerProperty(indexed=False, required=True)
    text = ndb.TextProperty(indexed=False, required=True)
