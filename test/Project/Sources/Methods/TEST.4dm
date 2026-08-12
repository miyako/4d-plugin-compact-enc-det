//%attributes = {}
C_OBJECT:C1216($params)
C_BLOB:C604($bytes)

$path:=Get 4D folder:C485(Current resources folder:K5:16)+"sample.html"
DOCUMENT TO BLOB:C525($path;$bytes)

$status:=CED Detect encoding ($bytes)

$params:=New object:C1471("ignore7bitMailEncodings";True:C214;"corpus";"QUERY_CORPUS")

$status:=CED Detect encoding ($bytes;$params)
