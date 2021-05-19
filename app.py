try:
    from PIL import Image
except ImportError:
    import Image
from pdf2image import convert_from_path, convert_from_bytes
import pytesseract
import pandas as pd
import numpy as np
import boto3
import io

s3_client = boto3.client('s3')

def image_to_data(img):
	data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, lang="deu")
	## get Price Image
	startIndex = data['text'].index('Zahlungspositionen')
	endIndex = data['text'].index('Summe')
	(x, y, w, h) =  (data['left'][startIndex], data['top'][startIndex], data['width'][startIndex], data['height'][startIndex])
	(h2, y2) =  (data['height'][endIndex], data['top'][endIndex])
	priceImg = img.crop((x, y, x + 400, y2+h2+5 ))
	#priceImg.save('/tmp/price.jpg')

	## get Destinations Image
	startIndex = data['text'].index('Reiseverbindung')
	endIndex = data['text'].index('Wichtige')
	y = data['top'][startIndex]
	y2 = data['top'][endIndex]
	destinationImg = img.crop((50, y-5, img.size[0], y2))
	#destinationImg.save('/tmp/destinations.jpg')

	return priceImg, destinationImg

def extract_costs(img, keyWord='Summe'):
	text = pytesseract.image_to_string(img, lang="deu")
	return text[ (text.find(keyWord) + len(keyWord)) : -2]

def extract_dates(img, keyWord='fahrt'):
	text = pytesseract.image_to_string(img, lang="deu")
	index = text.find(keyWord) + len(keyWord)
	return text[ index + 4 : index + 14]

def Extract_All_Stations_From_List(stationsList, keyWord='Hbf', returnEntries=False):
	stops = []
	for i in range(len(stationsList)):
		idx = stationsList[i].find(keyWord)
		if stationsList[i][ : idx - 1] not in stops:
			stops.append(stationsList[i][ : idx - 1])
	# [stops.append(stationsList[i][: stationsList[i].find('Hbf') - 1]) for i in range(len(stationsList)) if stationsList[i][: stationsList[i].find('Hbf') - 1] not in stops]
	if returnEntries: 
		if len(stops) > 2: # there was an changeover, thus a middle station
			returnStartStation	 	= stops[0]
			returnMiddleStation 	= stops[1]
			returnEndStation    	= stops[-1]
			return returnStartStation, returnMiddleStation, returnEndStation
		else: # no middle station
			returnStartStation 	= stops[0]
			returnMiddleStation 	= 'None'
			returnEndStation 		= stops[-1]
			return returnStartStation, returnMiddleStation, returnEndStation
	else: # only one way
		if len(stops) > 2: # there was an changeover, thus a middle station
			startStation 	= stops[0]
			middleStation 	= stops[1]
			endStation 	= stops[-1]
			return startStation, middleStation, endStation
		else: # no middle station
			startStation 	= stops[0]
			middleStation 	= 'None'
			endStation 	= stops[-1]
			return startStation, middleStation, endStation

def extract_stations(img, keyWord='Halt'):
	text = pytesseract.image_to_string(img, lang="deu")
	response = text[ (text.find(keyWord) + len(keyWord)) : -1]
	properStations 	= [station for station in response.split('\n') if len(station) > 1]
	del properStations[0] # delete header with 'Halt', 'Datum', 'Zeit', etc.

	## Check if a return train was also booked
	if any('fahrt' in entry for entry in properStations):
		returnDate = [entry[entry.find('fahrt') + 9 : entry.find('fahrt') + 19] for entry in properStations if 'fahrt' in entry][0]
		arrivalTrain = []
		returnTrain	 = []
		for i in range(len(properStations)): 
			if 'fahrt' in properStations[i]:
				arrivalTrain = properStations[ : i]
				returnTrain  = properStations[i+2 : ] # skip the Rueckfahrt and Halt, Datum rows and just take stations
				break

		## Take the Stations for each ride separetly
		start, middle, end = Extract_All_Stations_From_List(arrivalTrain)
		## now set bothWays Flag otherwise it won't fill properly
		start2, middle2, end2 = Extract_All_Stations_From_List(returnTrain, returnEntries=True)
		return [start, middle, end, start2, middle2, end2, returnDate]

	else: # only one way
		start, middle , end = Extract_All_Stations_From_List(properStations)
		return [start, middle, end]

def Create_Dataframe(travelInfoList):
	# [date, cost, start, middle, end, [startReturn, middleRe, endRe, returnDate]]
	header = ["Datum", "Kosten", "Startbahhof", "Zwischenstation", "Endbahnhof"]
	entries = np.array([ [travelInfoList[0]], [travelInfoList[1]], [travelInfoList[2]], [travelInfoList[3]], [travelInfoList[4]] ])

	if len(travelInfoList) > 6: # return train was booked
		ret = np.array([ [travelInfoList[-1]], ['see above'], [travelInfoList[5]], [travelInfoList[6]], [travelInfoList[7]] ])
		final_arr = np.vstack([entries.T, ret.T])
		return pd.DataFrame(final_arr, columns=header)

	else: # one way only
		return pd.DataFrame(entries.T, columns=header)

def Add_Delta_In_Dataframes(df_newEntry):
	## Load existing Excel File from S3 
	obj = s3_client.get_object(Bucket='lehmanl-storer', Key='PDF_TO_JPG/Fahrtkosten.csv')

	status = obj.get("ResponseMetadata", {}).get("HTTPStatusCode")
	if status == 200:
		df_read = pd.read_csv(obj.get("Body"))
		print("Successful S3 get_object response")
	else:
		print("Unsuccessful S3 get_object response. Status - {}".format(status))
		# file not present 
		return Upload_df_to_S3(df_newEntry)

	## check for differences
	differenceCounter = 0
	booleanCheckOfRows = df_read.isin(df_newEntry.values[0]) # type np.array with Trues and Falses
	for i in range(len(booleanCheckOfRows.values)):
		if False in booleanCheckOfRows.values[i]:
			differenceCounter += 1
	if differenceCounter == len(booleanCheckOfRows.values):
		print("Entry does NOT Exits --> Appending it to the DataFrame file")
		df_read = pd.concat([df_read, df_newEntry], ignore_index=True)
	else: 
		print("Entry does exists, DataFrame stays the same")

	df_read.sort_values('Datum')
	Upload_df_to_S3(df_read)

def Upload_df_to_S3(df, bucket='lehmanl-storer'):
	key = 'PDF_TO_JPG/Fahrtkosten.csv'
	csv_buffer = io.StringIO()
	df.to_csv(csv_buffer, index=False)
	s3_client.put_object(
		Bucket=bucket,
		Key=key,
		Body=csv_buffer.getvalue(),
		ContentType= 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
	)
	print("Successfully written Excel file into the S3 - {} Bucket.".format(bucket))

def upload_img_to_s3(img, filename):
	buffer = io.BytesIO()
	key = 'PDF_TO_JPG/Train_JPGs/' + filename[:-4] + '.jpg'
	img.save(buffer, "JPEG")
	buffer.seek(0) # rewind pointer back to start
	s3_client.put_object(
		Bucket='lehmanl-storer',
		Key=key,
		Body=buffer,
		ContentType='image/jpeg',
	)
	print("Uploaded Successfully into the Bucket ")

def handler(event, context):
	bucket = event['Records'][0]['s3']['bucket']['name']
	pdfPath = event['Records'][0]['s3']['object']['key']
	filename = pdfPath.split('/')[-1]
	download_path = '/tmp/{}'.format(filename)
	try:
		s3_client.download_file(bucket, pdfPath, download_path)
	except Exception as e: 
		print("There was a problem!!! \n{}".format(e))
	## Convert PDF to Image
	img = convert_from_path(download_path)
	upload_img_to_s3(img[0], filename)
	## Let the OCR Magic begin
	price, destination = image_to_data(img[0])
	cost = extract_costs(price)
	date = extract_dates(destination)
	stationsList = extract_stations(destination)

	## parse the stations list to feed the right travelinfo list
	if len(stationsList) > 3: # with return train booked
		travelInfoList = [date, cost, stationsList[0], stationsList[1], stationsList[2], stationsList[3], stationsList[4], stationsList[5], stationsList[6]]
		df = Create_Dataframe(travelInfoList)
	else: # only one way 
		travelInfoList = [date, cost, stationsList[0], stationsList[1], stationsList[2]]
		df = Create_Dataframe(travelInfoList)
	print(df)
	Add_Delta_In_Dataframes(df)	