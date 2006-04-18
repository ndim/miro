import cPickle

import schema as schema_mod

# _BootStrapClass is used to as the initial class when we restore an object.
class _BootStrapClass:
    pass

class SavableObject:
    """Object that can be safely pickled and saved to disk.  

    Member variables:

    classString -- specifies the class this object was converted from.  
    savedData -- dict that stores the data we've saved.
    
    The SavableObject class is guarenteed to never change.  This means we can
    always safely unpickle them.
    """

    def __init__(self, classString):
        self.classString = classString
        self.savedData = {}

class ConverterBase(object):
    """Base class for SavableConverter and SavableUnconverter.  It handles the
    common tasks relating to converting the database to/from SavableObjects.
    This include stuff like walking the object hierarchy, handling circular
    references, keeping track of the path, etc.

    The subclasses of ConverterBase are responsible for creating a
    convertObject method, and adding validation to the convertData method
    (SavableConverter does validation at the begining, SavableUnconverter does
    it at the end).
    """

    def __init__(self, objectSchemas=None):
        """Contruct a converter.  object schemas is a list of ObjectSchema
        objects to use.  If none is given (the default), the schemas will be
        taken from schema.objectSchemas.
        """

        if objectSchemas is None:
            objectSchemas = schema.objectSchemas

        self.objectSchemaLookup = {}
        self.classesToStrings = {}
        self.stringsToClasses = {}
        for os in objectSchemas:
            self.stringsToClasses[os.classString] = os.klass
            self.classesToStrings[os.klass] = os.classString
            self.objectSchemaLookup[os.klass] = os

    def convertData(self, data, schema, memory, path=""):
        """Convert one piece of data.

        Arguments:
            data -- piece of data to be converted
            schema -- schema that the data should conform to
            memory -- dict containing the objects that we've already
                converted.  It's used to handle circular references.
            path -- string describing how we got to this object.  Its format
                is totally arbitrary, we just use it to help debug validation
                errors.
        """

        try:
            self.preValidate(data, schema)
        except schema_mod.ValidationError, e:
            self.handleValidationError(e, data, path, schema)

        if data is None:
            rv = None
        elif isinstance(schema, schema_mod.SchemaSimpleItem):
            rv = data
        elif isinstance(schema, schema_mod.SchemaList):
            rv = self.convertList(data, schema, memory, path)
        elif isinstance(schema, schema_mod.SchemaDict):
            rv = self.convertDict(data, schema, memory, path)
        elif isinstance(schema, schema_mod.SchemaObject):
            rv = self.convertObject(data, schema, memory, path)
        else:
            raise ValueError("%s has an unknown SchemaItem type" % schema)

        try:
            self.postValidate(rv, schema)
        except schema_mod.ValidationError, e:
            self.handleValidationError(e, data, path, schema)
        return rv

    def convertList(self, list, schema, memory, path):
        childSchema = schema.childSchema
        rv = []
        for i in xrange(len(list)):
            child = list[i]
            newPath = path + "\n[%d] -> %s" % (i, child)
            rv.append(self.convertData(child, childSchema, memory, newPath))
        return rv

    def convertDict(self, dict, schema, memory, path):
        keySchema = schema.keySchema
        valueSchema = schema.valueSchema
        rv = {}
        for key, value in dict.items():
            # convert the key
            newPath = path + "\nkey: %s" % key
            newKey = self.convertData(key, keySchema, memory, newPath)
            # convert the value
            newPath = path + "\n{%s} -> %s" % (key, value)
            newValue = self.convertData(value, valueSchema, memory, newPath)
            # put it together
            rv[newKey] = newValue
        return rv

    def convertObjectList(self, objects):
        """Convert a list of objects.  This is the top-level method that the
        saveDatabase and restoreDatabase methods use to convert a list of
        DDBObjects to/from SavableObjects.
        """

        retval = []
        memory = {}
        for object, schema in self.prepareObjectList(objects):
            path = "%s" % object
            retval.append(self.convertData(object, schema, memory, path))
        return retval

    def convertObject(self, object, schema, memory, path):
        if id(object) in memory:
            return memory[id(object)]

        # NOTE: we can't use the schema variable for anything here because
        # object might be a subclass of the class specified in schema.
        # Instead we call getObjectSchema() and use the info from there.

        objectSchema = self.getObjectSchema(object)
        convertedObject = self.makeNewConvert(objectSchema.classString)
        memory[id(object)] = convertedObject

        for name, schema in objectSchema.fields:
            data = self.getSourceAttr(object, name)
            newPath = path + "\n%s -> %s" % (name, data)
            convertedData = self.convertData(data, schema, memory, newPath)
            self.setTargetAttr(convertedObject, name, convertedData)
        return convertedObject

    # Methods that may be overridden by SavableConverter/SavableUnconverter
    def preValidate(self, data, schema):
        """Can be used to validate that a piece of data that is about to be
        converted matches the schema for it.
        """
        pass

    def postValidate(self, converted, schema):
        """Can be used to validate that a converted piece of data matches the
        schema for it.
        """
        pass

    def getSourceAttr(self, object, attrName):
        """Retrive the value of an attribute on a source object."""
        return getattr(object, attrName)

    def setTargetAttr(self, object, attrName, attrValue):
        """Set the value of an attribute on a target object."""
        setattr(object, attrName, attrValue)

    def handleValidationError(self, e, object, path, schema):
        reason = e.args[0]
        message = """\
Error validating object %r

Path:
%s

Schema: %s
Reason: %s""" % (object, path, schema, reason)
        raise schema_mod.ValidationError(message)

    # methods below here *must* be implemented by subclasses
    def getObjectSchema(self, object):
        """Get an ObjectSchema for a object to be converted."""

        raise NotImplementError()

    def prepareObjectList(self, objectList):
        """Do the prep work for convertObjectList.

        Given a list of objects, return a list of (object, schema) tuples
        that should be converted.
        """

        raise NotImplementError()

    def makeNewConvert(self, classString):
        """Construct a new object to use as our converted value.

        SavableConverter returns a SavableObject, SavableUnconverter returns a
        DDBObject.
        """
        raise NotImplementError()

class SavableConverter(ConverterBase):
    """Used to convert a list of DDBObjects into a list with the same
    structure, but with DDBObject converted to SavableObjects.
    """

    def prepareObjectList(self, objectList):
        rv = []
        for object in objectList:
            if object.__class__ in self.classesToStrings:
                rv.append((object, schema_mod.SchemaObject(object.__class__)))
        return rv

    def getObjectSchema(self, object):
        return self.objectSchemaLookup[object.__class__]

    def preValidate(self, data, schema):
        schema.validate(data)

    def makeNewConvert(self, classString):
        return SavableObject(classString)

    def setTargetAttr(self, savable, attrName, attrValue):
        savable.savedData[attrName] = attrValue

class SavableUnconverter(ConverterBase):
    """Used to reverse the work of SavableConverter."""

    def prepareObjectList(self, objectList):
        rv = []
        for o in objectList:
            klass = self.stringsToClasses[o.classString]
            rv.append((o, schema_mod.SchemaObject(klass)))
        return rv

    def getObjectSchema(self, object):
        klass = self.stringsToClasses[object.classString]
        return self.objectSchemaLookup[klass]

    def makeNewConvert(self, classString):
        restored = _BootStrapClass()
        restored.__class__ = self.stringsToClasses[classString]
        return restored

    def getSourceAttr(self, savable, attrName):
        return savable.savedData[attrName]

    def postValidate(self, converted, schema):
        schema.validate(converted)

    def handleValidationError(self, e, object, path, schema):
        reason = e.args[0]
        message = """\
Error validating object %r
Will use data anyway, bad things may happen soon

Path:
%s

Schema: %s
Reason: %s""" % (object, path, schema, reason)
        raise schema.ValidationWarning(message)

def saveObjectList(objects, objectSchemas=None):
    """Transform a list of objects into something that we can save to disk.
    This means converting any DDBObjects into SavebleObjects.
    """

    saver = SavableConverter(objectSchemas)
    return saver.convertObjectList(objects)

def restoreObjectList(savedObjects, objectSchemas=None):
    restorer = SavableUnconverter(objectSchemas)
    restorer.objectSchemas = objectSchemas
    return restorer.convertObjectList(savedObjects)

def saveDatabase(objects, pathname, objectSchemas=None):
    savableObjects = saveObjectList(objects, objectSchemas)
    toPickle = (schema_mod.VERSION, savableObjects)
    f = open(pathname, 'w')
    try:
        cPickle.dump(toPickle, f)
    finally:
        f.close()

def restoreDatabase(pathname, objectSchemas=None):
    f = open(pathname, 'r')
    try:
        version, savedObjects = cPickle.load(f)
    finally:
        f.close()

    # should do upgrade stuff here

    return restoreObjectList(savedObjects, objectSchemas)

