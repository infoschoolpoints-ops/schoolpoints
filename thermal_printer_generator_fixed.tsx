import React, { useState, useRef } from 'react';
import { Download, FileImage, FileText, Info } from 'lucide-react';

export default function ThermalPrinterGenerator() {
  const [imageFile, setImageFile] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [hebrewText, setHebrewText] = useState('חנות רות שלי\nנופית');
  const [status, setStatus] = useState('');
  const canvasRef = useRef(null);

  // המרת תמונה ל-bitmap תרמי (מותאם למדפסת Verifone MX980L)
  const convertImageToBitmap = async (imgFile) => {
    return new Promise((resolve, reject) => {
      const img = new window.Image();
      const reader = new FileReader();
      
      reader.onload = (e) => {
        img.onload = () => {
          const canvas = canvasRef.current;
          const ctx = canvas.getContext('2d');
          
          // גודל מדויק למדפסת שלך: 352x80 פיקסלים (44x10 bytes)
          const WIDTH = 352;
          const HEIGHT = 80;
          const X_BYTES = 44;
          const Y_SLICES = 10;
          
          canvas.width = WIDTH;
          canvas.height = HEIGHT;
          
          // חישוב סקייל ומיקום מרכז
          const scale = Math.min(WIDTH / img.width, HEIGHT / img.height) * 0.75;
          const newWidth = Math.max(1, Math.floor(img.width * scale));
          const newHeight = Math.max(1, Math.floor(img.height * scale));
          const pasteX = (WIDTH - newWidth) // 2;
          const pasteY = (HEIGHT - newHeight) // 2;
          
          // מילוי רקע לבן
          ctx.fillStyle = 'white';
          ctx.fillRect(0, 0, WIDTH, HEIGHT);
          
          // המרה לשחור-לבן והחלקה
          ctx.filter = 'blur(0.5px)';
          ctx.drawImage(img, pasteX, pasteY, newWidth, newHeight);
          
          const imageData = ctx.getImageData(0, 0, WIDTH, HEIGHT);
          const pixels = imageData.data;
          
          // סף גבוה לצפיפות נמוכה (כמו ALL4SHOP)
          const threshold = 170;
          const bitmap = [];
          
          // המרה לפורמט bitmap של מדפסת (row-major, MSB-first)
          for (let y = 0; y < HEIGHT; y++) {
            for (let byteX = 0; byteX < X_BYTES; byteX++) {
              let byte = 0;
              for (let bit = 0; bit < 8; bit++) {
                const x = byteX * 8 + bit;
                const i = (y * WIDTH + x) * 4;
                const brightness = (pixels[i] + pixels[i + 1] + pixels[i + 2]) / 3;
                if (brightness < threshold) {
                  byte |= (0x80 >> bit); // MSB-first
                }
              }
              bitmap.push(byte);
            }
          }
          
          resolve({ WIDTH, HEIGHT, X_BYTES, Y_SLICES, bitmap });
        };
        img.src = e.target.result;
      };
      
      reader.onerror = reject;
      reader.readAsDataURL(imgFile);
    });
  };

  // המרת טקסט עברי ל-CP862
  const hebrewToCP862 = (text) => {
    const cp862Map = {
      'א': 0x80, 'ב': 0x81, 'ג': 0x82, 'ד': 0x83, 'ה': 0x84,
      'ו': 0x85, 'ז': 0x86, 'ח': 0x87, 'ט': 0x88, 'י': 0x89,
      'ך': 0x8A, 'כ': 0x8B, 'ל': 0x8C, 'ם': 0x8D, 'מ': 0x8E,
      'ן': 0x8F, 'נ': 0x90, 'ס': 0x91, 'ע': 0x92, 'ף': 0x93,
      'פ': 0x94, 'ץ': 0x95, 'צ': 0x96, 'ק': 0x97, 'ר': 0x98,
      'ש': 0x99, 'ת': 0x9A, ' ': 0x20, '\n': 0x0A,
      '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
      '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
      ':': 0x3A, '.': 0x2E
    };
    
    const bytes = [];
    for (let char of text) {
      if (cp862Map[char] !== undefined) {
        bytes.push(cp862Map[char]);
      } else if (char.charCodeAt(0) < 128) {
        bytes.push(char.charCodeAt(0));
      }
    }
    return bytes;
  };

  // יצירת קובץ הדפסה (מותאם למדפסת Verifone MX980L)
  const generatePrintFile = async () => {
    try {
      setStatus('מעבד...');
      const commands = [];
      
      // אתחול
      commands.push(0x1B, 0x40); // ESC @
      
      // אם יש תמונה
      if (imageFile) {
        const { WIDTH, HEIGHT, X_BYTES, Y_SLICES, bitmap } = await convertImageToBitmap(imageFile);
        
        // פקודת גרפיקה GS * - מותאם למדפסת שלך
        commands.push(0x1D, 0x2A, X_BYTES, Y_SLICES); // GS * 44 10
        
        // הוספת 517 בייטים של אפסים (padding כמו ALL4SHOP)
        for (let i = 0; i < 517; i++) {
          commands.push(0x00);
        }
        
        // הוספת נתוני ה-bitmap
        bitmap.forEach(byte => commands.push(byte));
        
        // מילוי השאר באפסים אם צריך (עד 3520 בייטים סה"כ)
        const totalBytes = X_BYTES * Y_SLICES * 8; // 3520
        const currentSize = 517 + bitmap.length;
        for (let i = currentSize; i < totalBytes; i++) {
          commands.push(0x00);
        }
        
        // הדפסת הלוגו שהוגדר
        commands.push(0x1D, 0x2F, 0x01); // GS / 1
        commands.push(0x0A, 0x0A, 0x0A); // שורות ריקות
      }
      
      // הוספת טקסט
      commands.push(0x1B, 0x21, 0x00, 0x0A); // טקסט רגיל
      
      // טקסט מודגש וגדול
      commands.push(0x1B, 0x21, 0x08); // מודגש
      commands.push(0x1B, 0x21, 0x30); // גדול
      
      const textBytes = hebrewToCP862(hebrewText);
      textBytes.forEach(b => commands.push(b));
      
      // איפוס עיצוב
      commands.push(0x0A, 0x1B, 0x21, 0x00);
      
      // חיתוך נייר
      commands.push(0x0A, 0x0A, 0x0A);
      commands.push(0x1D, 0x56, 0x31, 0x0A); // GS V 1
      
      // המרה ל-Uint8Array והורדה
      const uint8Array = new Uint8Array(commands);
      const blob = new Blob([uint8Array], { type: 'application/octet-stream' });
      const url = URL.createObjectURL(blob);
      
      const a = document.createElement('a');
      a.href = url;
      a.download = 'thermal_print_verifone.bin';
      a.click();
      
      URL.revokeObjectURL(url);
      setStatus('הקובץ נוצר בהצלחה!');
    } catch (error) {
      setStatus('שגיאה: ' + error.message);
      console.error(error);
    }
  };

  const handleImageUpload = (e) => {
    const file = e.target.files[0];
    if (file) {
      setImageFile(file);
      const reader = new FileReader();
      reader.onload = (e) => setImagePreview(e.target.result);
      reader.readAsDataURL(file);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 p-6" dir="rtl">
      <div className="max-w-4xl mx-auto">
        <div className="bg-white rounded-2xl shadow-xl p-8">
          <h1 className="text-3xl font-bold text-gray-800 mb-2 flex items-center gap-3">
            <FileText className="text-indigo-600" size={32} />
            מחולל קבצי הדפסה תרמית (Verifone MX980L)
          </h1>
          <p className="text-gray-600 mb-8">צור קבצי הדפסה מותאמים למדפסת Verifone MX980L</p>

          {/* אזור מידע */}
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
            <div className="flex items-start gap-3">
              <Info className="text-blue-600 mt-1 flex-shrink-0" size={20} />
              <div className="text-sm text-blue-800">
                <p className="font-semibold mb-1">מה השתנה?</p>
                <ul className="list-disc list-inside space-y-1">
                  <li>גודל תמונה: 352x80 פיקסלים (במקום 576)</li>
                  <li>מבנה GS *: 44x10 bytes (במקום דינמי)</li>
                  <li>Padding של 517 בייטים (כמו ALL4SHOP)</li>
                  <li>קידוד MSB-first (row-major)</li>
                </ul>
              </div>
            </div>
          </div>

          {/* העלאת תמונה */}
          <div className="mb-6">
            <label className="block text-lg font-semibold text-gray-700 mb-3 flex items-center gap-2">
              <FileImage size={20} />
              לוגו / תמונה (אופציונלי)
            </label>
            <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-indigo-400 transition-colors">
              <input
                type="file"
                accept="image/*"
                onChange={handleImageUpload}
                className="hidden"
                id="imageUpload"
              />
              <label
                htmlFor="imageUpload"
                className="cursor-pointer flex flex-col items-center gap-3"
              >
                {imagePreview ? (
                  <img
                    src={imagePreview}
                    alt="Preview"
                    className="max-h-48 rounded border border-gray-300"
                  />
                ) : (
                  <>
                    <FileImage size={48} className="text-gray-400" />
                    <span className="text-gray-600">לחץ להעלאת תמונה</span>
                  </>
                )}
              </label>
            </div>
          </div>

          {/* טקסט עברי */}
          <div className="mb-6">
            <label className="block text-lg font-semibold text-gray-700 mb-3">
              טקסט עברי
            </label>
            <textarea
              value={hebrewText}
              onChange={(e) => setHebrewText(e.target.value)}
              className="w-full h-32 p-4 border-2 border-gray-300 rounded-lg focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 transition-all text-right font-semibold text-lg"
              placeholder="הכנס טקסט עברי..."
              dir="rtl"
            />
          </div>

          {/* Canvas נסתר לעיבוד תמונות */}
          <canvas ref={canvasRef} className="hidden" />

          {/* כפתור יצירה */}
          <button
            onClick={generatePrintFile}
            className="w-full bg-gradient-to-r from-indigo-600 to-blue-600 text-white py-4 rounded-lg font-bold text-lg hover:from-indigo-700 hover:to-blue-700 transition-all shadow-lg hover:shadow-xl flex items-center justify-center gap-3"
          >
            <Download size={24} />
            צור קובץ הדפסה (Verifone)
          </button>

          {/* סטטוס */}
          {status && (
            <div className={`mt-4 p-4 rounded-lg text-center font-semibold ${
              status.includes('שגיאה') 
                ? 'bg-red-100 text-red-700' 
                : 'bg-green-100 text-green-700'
            }`}>
              {status}
            </div>
          )}

          {/* הסבר טכני */}
          <div className="mt-8 pt-6 border-t border-gray-200">
            <h3 className="font-bold text-gray-800 mb-3">פרטים טכניים (מותאם ל-Verifone MX980L):</h3>
            <div className="bg-gray-50 rounded-lg p-4 text-sm space-y-2 text-gray-700">
              <p><strong>מדפסת:</strong> Verifone MX980L (Cash Printer)</p>
              <p><strong>פרוטוקול:</strong> ESC/POS</p>
              <p><strong>קידוד עברי:</strong> CP862</p>
              <p><strong>גודל תמונה:</strong> 352x80 פיקסלים (44x10 bytes)</p>
              <p><strong>מבנה נתונים:</strong> 517 bytes padding + bitmap data</p>
              <p><strong>פקודות עיקריות:</strong></p>
              <ul className="list-disc list-inside mr-4">
                <li>1B 40 - אתחול מדפסת</li>
                <li>1D 2A 44 10 - הגדרת גרפיקה (352x80)</li>
                <li>1D 2F 01 - הדפסת גרפיקה שהוגדרה</li>
                <li>1B 21 - עיצוב טקסט</li>
                <li>1D 56 31 - חיתוך נייר</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
