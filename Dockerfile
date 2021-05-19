FROM public.ecr.aws/lambda/python:3.8 as build

WORKDIR /app
# Install all necessary libraries
RUN yum -y install tar make wget gzip openjpeg-devel libjpeg-devel fontconfig-devel libtiff-devel libpng-devel xz gcc gcc-c++ epel-release zip cmake3

# Download and uncompress OpenJPEG
RUN wget https://github.com/uclouvain/openjpeg/archive/v2.3.1/openjpeg-2.3.1.tar.gz && \
    gzip -d openjpeg-2.3.1.tar.gz && \
    tar xvf openjpeg-2.3.1.tar

# Build library
RUN mkdir -p openjpeg-2.3.1/build && \
    cd openjpeg-2.3.1/build && \
    cmake3 -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_INSTALL_PREFIX=/usr \
      -DBUILD_STATIC_LIBS=OFF .. && \
    make && \
    make install
RUN cd /app

# Install Poppler now
RUN wget https://poppler.freedesktop.org/poppler-0.59.0.tar.xz && \
    tar xJvf poppler-0.59.0.tar.xz && \
    cd poppler-0.59.0/ && \
    ./configure --enable-static --enable-build-type=release && \
    make && \
    make install

RUN cd /app && \
    mkdir -p package/lib package/bin

# Copy openJPEG
RUN cp /usr/lib64/{libopenjpeg.so.1,libpng15.so.15,libtiff.so.5,libjpeg.so.62,libfreetype.so.6,libfontconfig.so.1,libjbig.so.2.0} /app/package/lib
RUN cp /lib64/{libz.so.1,libexpat.so.1} /app/package/lib

# Copy Poppler
RUN cp poppler-0.59.0/poppler/.libs/libpoppler.so.70 /app/package/lib
RUN cp poppler-0.59.0/utils/.libs/{pdftotext,pdfinfo,pdfseparate,pdftoppm} /app/package/bin

# -- Install Tesseract -- #
RUN yum install -y git

RUN git clone https://github.com/bweigel/aws-lambda-tesseract-layer.git
RUN cp /app/aws-lambda-tesseract-layer/ready-to-use/amazonlinux-2/bin/* /app/package/bin/ && \
    cp /app/aws-lambda-tesseract-layer/ready-to-use/amazonlinux-2/lib/* /app/package/lib/ && \
    cp -R /app/aws-lambda-tesseract-layer/ready-to-use/amazonlinux-2/tesseract /app/package/tesseract

FROM public.ecr.aws/lambda/python:3.8

COPY --from=build /app/package/ /opt/
RUN yum install -y fontconfig fontconfig-devel openjpeg-devel libjpeg-devel  libtiff-devel libpng-devel
RUN pip install pdf2image pytesseract numpy pandas boto3

COPY app.py   ./

CMD ["app.handler"]